"""Save the default video and route the user's bare Fastfetch command to it."""
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile


_LAUNCHER_HEADER = "#!/bin/sh\n# PlayBash Fastfetch launcher\n"
CONTROL_ENV = "PLAYBASH_LOGO_SOCKET"
READY_ENV = "PLAYBASH_LOGO_SHELL_READY"
_BASH_START = "# >>> PlayBash Fastfetch >>>"
_BASH_END = "# <<< PlayBash Fastfetch <<<"
BASH_FASTFETCH_FUNCTION = ('fastfetch() {\n'
                          '    if [[ -x "$HOME/.local/bin/fastfetch" ]]; then\n'
                          '        "$HOME/.local/bin/fastfetch" "$@"\n'
                          '    else\n'
                          '        command fastfetch "$@"\n'
                          '    fi\n'
                          '}\n')


def _selection_path():
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / "playbash" / "fastfetch.json"


def _launcher_path():
    return Path.home() / ".local" / "bin" / "fastfetch"


def _saved_framing_is_valid(framing):
    return (isinstance(framing, list) and len(framing) == 3
            and all(type(value) in (int, float) and -1e8 < value < 1e8 for value in framing)
            and 0 < framing[0] <= 3)


def _is_managed(path):
    if path.is_symlink() or not path.is_file():
        return False
    with path.open("rb") as launcher:
        return launcher.read(len(_LAUNCHER_HEADER)) == _LAUNCHER_HEADER.encode()


def native_fastfetch():
    launcher = _launcher_path()
    managed = _is_managed(launcher)
    launcher = launcher.resolve()
    # Include the customary system paths for the launcher when Bash calls it
    # at startup, before the user's PATH setup runs.
    for directory in dict.fromkeys([*os.get_exec_path(), *os.defpath.split(os.pathsep)]):
        command = shutil.which("fastfetch", path=directory or os.curdir)
        if command and not (managed and Path(command).resolve() == launcher):
            return str(Path(command).absolute())
    return None


def load_default_logo():
    try:
        data = json.loads(_selection_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("Invalid saved Fastfetch logo. Select a video again.") from error
    if not isinstance(data, dict) or not isinstance(data.get("video"), str) or not data["video"]:
        raise ValueError("Invalid saved Fastfetch logo. Select a video again.")
    framing = data.get("framing")
    if framing is not None:
        if not _saved_framing_is_valid(framing):
            raise ValueError("Invalid saved Fastfetch framing. Select a video again.")
        framing = tuple(framing)
    return data["video"], framing


def _atomic_write(path, text, *, mode=None, replace=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    output = tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False)
    temporary = Path(output.name)
    try:
        with output:
            output.write(text)
        if mode is not None:
            temporary.chmod(mode)
        if replace:
            temporary.replace(path)
        else:
            os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _install_launcher(executable):
    path = _launcher_path()
    managed = _is_managed(path)
    if os.path.lexists(path) and not managed:
        raise ValueError(f"A different Fastfetch launcher already exists at {path}.")
    python = shlex.quote(sys.executable)
    native = shlex.quote(executable)
    script = (
        _LAUNCHER_HEADER
        + 'if [ "$#" -eq 0 ] && [ -t 0 ] && [ -t 1 ] &&\n'
          '   [ -r "${XDG_CONFIG_HOME:-$HOME/.config}/playbash/fastfetch.json" ] &&\n'
        + f'   {{ [ -z "${{{CONTROL_ENV}:-}}" ] || [ "${{{READY_ENV}:-}}" = 1 ]; }}; then\n'
        + f"    {python} -m playbash fastfetch && exit 0\n"
        + "fi\n"
        + f'exec {native} "$@"\n'
    )
    if managed and path.read_text(encoding="utf-8") == script:
        return
    try:
        _atomic_write(path, script, mode=0o755, replace=managed)
    except FileExistsError:
        if not _is_managed(path):
            raise ValueError(f"A different Fastfetch launcher already exists at {path}.") from None


def _bash_hook():
    return (
        f"{_BASH_START}\n"
        f'if [[ $- == *i* && -z ${{{CONTROL_ENV}:-}} &&\n'
        '      -x "$HOME/.local/bin/fastfetch" ]] &&\n'
        '      ! declare -F fastfetch >/dev/null && ! alias fastfetch >/dev/null 2>&1; then\n'
        f'{BASH_FASTFETCH_FUNCTION}'
        'fi\n'
        f"{_BASH_END}\n"
    )


def _read_bashrc():
    path = Path.home() / ".bashrc"
    try:
        with path.open("r", encoding="utf-8", newline="") as startup:
            return path.resolve(), startup.read()
    except FileNotFoundError:
        return path, None


def _install_bash_hook():
    path, current = _read_bashrc()
    if current is None:
        return
    if _BASH_START in current:
        return
    # Prepend so existing startup calls can see the launcher even before they
    # update PATH. Keep all of the user's existing startup code and file mode.
    _atomic_write(path, _bash_hook() + current, mode=path.stat().st_mode & 0o777)


def save_default_logo(video, framing, executable):
    _install_launcher(executable)
    if Path(os.environ.get("SHELL", "bash")).name == "bash":
        _install_bash_hook()
    data = {"video": str(video), "framing": framing}
    _atomic_write(_selection_path(), json.dumps(data, indent=2) + "\n")


def reset_default_logo():
    _selection_path().unlink(missing_ok=True)
    if not _is_managed(_launcher_path()):
        return
    path, current = _read_bashrc()
    hook = _bash_hook()
    if current is not None and current.startswith(hook):
        _atomic_write(path, current.removeprefix(hook), mode=path.stat().st_mode & 0o777)
    # Existing shells can have this path cached. The launcher now forwards
    # every call to the original command because the selection is gone.
