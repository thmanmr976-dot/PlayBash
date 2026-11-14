"""Keep a logo and an interactive shell in the same terminal."""
import codecs
import errno
import fcntl
import os
from pathlib import Path
import pty
import pwd
import re
import select
import shutil
import signal
import socket
import struct
import sys
import tempfile
import termios
import time
import tty
import unicodedata

from playbash.core.renderer import RESET_FOREGROUND, ansi_lines
from playbash.core.logo_default import BASH_FASTFETCH_FUNCTION, CONTROL_ENV, READY_ENV
from playbash.core.input import PlaybackStopped


_CURSOR_REPLY = re.compile(rb"\x1b\[(\d+);(\d+)R")
_CSI = re.compile(r"\x1b\[([0-?]*)([ -/]*)([@-~])")
_STRING_END = re.compile(r"\x07|\x1b\\")
_KEY_ESCAPE = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*|O)([@-~])")
_KEY_PREFIX = re.compile(rb"\x1b(?:\[[0-?]*[ -/]*|O)?")
_ARROWS = {b"A": "up", b"B": "down", b"C": "right", b"D": "left"}
_ZOOM_KEYS = {b"+": "+", b"-": "-"}
_KEYPAD_ZOOM = {b"k": "+", b"m": "-"}


class LogoViewport:
    """Track the logo as shell output scrolls. Suspend on unknown screen changes."""

    def __init__(self, layout, grid, row, col):
        self.layout = layout
        self.grid = grid
        self.top = row - layout.rows_above_cursor
        self.row = row
        self.col = col
        self.active = self.top >= 0
        self.alternate = False
        self.wrap_pending = False
        self.autowrap = True
        self.hyperlink = False
        self.tail = ""
        self.style = []
        self.saved = None
        self._decode = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def _touch(self, row, start, end):
        logo = self.layout.logo
        left = self.layout.column
        if self.top <= row < self.top + logo.rows and start < left + logo.columns and end > left:
            self.active = False

    def _linefeed(self):
        self.wrap_pending = False
        if self.row == self.grid.rows - 1:
            self.top -= 1
            if self.top + self.layout.logo.rows <= 0:
                self.active = False
        else:
            self.row += 1

    def _text(self, ch):
        if ch == "\r":
            self.col = 0
            self.wrap_pending = False
        elif ch in "\n\v\f":
            self._linefeed()
        elif ch == "\b":
            if not self.wrap_pending:
                self.col = max(0, self.col - 1)
            self.wrap_pending = False
        elif ch == "\t":
            self.col = min(self.grid.columns - 1, (self.col // 8 + 1) * 8)
            self.wrap_pending = False
        elif ch in ("\u200d", "\ufe0f", "\ufffd"):
            # Cluster width or malformed UTF-8 may differ from the terminal's
            # cursor width. Keep relaying input and leave the last logo frame.
            self.active = False
        elif unicodedata.category(ch) in ("Mn", "Me") or unicodedata.combining(ch):
            self._touch(self.row, max(0, self.col - 1), self.col)
        elif unicodedata.category(ch) not in ("Cc", "Cf"):
            width = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
            if self.autowrap and (self.wrap_pending or self.col + width > self.grid.columns):
                self.col = 0
                self._linefeed()
            self._touch(self.row, self.col, self.col + width)
            self.wrap_pending = self.autowrap and self.col + width >= self.grid.columns
            self.col = min(self.grid.columns - 1, self.col + width)

    def _save_cursor(self):
        self.saved = (self.row, self.col, self.wrap_pending, self.style.copy())

    def _restore_cursor(self):
        if self.saved is None:
            self.active = False
        else:
            self.row, self.col, self.wrap_pending, self.style = self.saved

    def _csi(self, command):
        params, intermediate, code = command.groups()
        if code in ("h", "l") and params.startswith("?"):
            modes = params[1:].split(";")
            enabled = code == "h"
            if "1049" in modes:
                self.alternate = enabled
            if self.alternate:
                return
            if "7" in modes:
                self.autowrap = enabled
                self.wrap_pending = False
            known = {"7", "12", "25", "1000", "1002", "1003", "1004", "1006", "1015",
                     "1049", "2004", "2026"}
            if set(modes) - known or "2026" in modes:
                self.active = False
            return
        if self.alternate:
            return
        if code == "m":
            if params and params[0] in "><=?":
                return  # Input protocol setting, not a visual rendition.
            if params in ("", "0"):
                self.style = []
            else:
                self.style.append(command[0])
                if len(self.style) > 64:
                    self.active = False
            return
        if code in ("n", "c", "q") or (code == "u" and params.startswith((">", "<", "?", "="))):
            return
        if intermediate or not re.fullmatch(r"[\d;]*", params):
            self.active = False
            return
        nums = [int(value or 0) for value in params.split(";")]
        n = nums[0] or 1
        if code in "ABCDGHEFf`ade":
            self.wrap_pending = False
            if code in "ADEF":
                if code == "D":
                    self.col -= n
                else:
                    self.row += n if code == "E" else -n
                    if code in "EF":
                        self.col = 0
            elif code in "Be":
                self.row += n
            elif code in "Ca":
                self.col += n
            elif code in "G`":
                self.col = n - 1
            elif code == "d":
                self.row = n - 1
            else:  # H/f: absolute row and column.
                self.row, self.col = n - 1, (nums[1] or 1) - 1 if len(nums) > 1 else 0
            self.row = min(self.grid.rows - 1, max(0, self.row))
            self.col = min(self.grid.columns - 1, max(0, self.col))
        elif code == "K":
            self._touch(self.row, self.col if nums[0] == 0 else 0,
                        self.col + 1 if nums[0] == 1 else self.grid.columns)
            self.wrap_pending = False
        elif code == "J":
            end = self.top + self.layout.logo.rows - 1
            if nums[0] >= 2 or (nums[0] == 0 and self.row < end) or (nums[0] == 1 and self.row > self.top):
                self.active = False
            elif nums[0] == 0:
                self._touch(self.row, self.col, self.grid.columns)
            else:
                self._touch(self.row, 0, self.col + 1)
            self.wrap_pending = False
        elif code in "@PX":
            self._touch(self.row, self.col, self.col + n if code == "X" else self.grid.columns)
        elif code == "s" and not params:
            self._save_cursor()
        elif code == "u" and not params:
            self._restore_cursor()
        else:
            # Changing scroll margins, origin mode, or unsupported geometry
            # must never let the renderer write over the user's command output.
            self.active = False

    def feed(self, data):
        if not self.active and not self.alternate:
            return
        text = self.tail + self._decode.decode(data)
        index = 0
        while index < len(text):
            if text[index] != "\x1b":
                if not self.alternate:
                    self._text(text[index])
                index += 1
                continue
            if index + 1 == len(text):
                break
            kind = text[index + 1]
            if kind == "[":
                command = _CSI.match(text, index)
                if command is None:
                    break
                self._csi(command)
                index = command.end()
            elif kind in "]P_^":
                end = _STRING_END.search(text, index + 2)
                if end is None:
                    break
                if not self.alternate and kind == "]" and text.startswith("\x1b]8;", index):
                    fields = text[index + 2:end.start()].split(";", 2)
                    self.hyperlink = len(fields) == 3 and bool(fields[2])
                if not self.alternate and kind != "]":
                    self.active = False
                index = end.end()
            elif kind in "()":
                if index + 2 == len(text):
                    break
                if not self.alternate and text[index + 2] != "B":
                    self.active = False
                index += 3
            else:
                if not self.alternate:
                    if kind == "7":
                        self._save_cursor()
                    elif kind == "8":
                        self._restore_cursor()
                    elif kind == "D":
                        self._linefeed()
                    elif kind == "E":
                        self.col = 0
                        self._linefeed()
                    elif kind not in "=>":
                        self.active = False
                index += 2
            if not self.active and not self.alternate:
                break
        self.tail = text[index:]
        if len(self.tail) > 16384:
            self.tail = ""
            self.active = False

    def control_ready(self):
        return not (self.alternate or self.tail or self._decode.getstate()[0])

    def visible_rows(self):
        if not self.active or self.wrap_pending or self.hyperlink or not self.control_ready():
            return None
        left = self.layout.column
        bottom = self.top + self.layout.logo.rows
        if self.top <= self.row < bottom and left <= self.col < left + self.layout.logo.columns:
            return None
        first, end = max(0, -self.top), min(self.layout.logo.rows, self.grid.rows - self.top)
        return (first, end) if first < end else None

    def paint(self, frame):
        visible = self.visible_rows()
        if visible is None:
            return b""
        first, end = visible
        left = self.layout.column
        updates = [
            f"\x1b[{self.top + i + 1};{left + 1}H{frame[i]}"
            for i in range(first, end)
        ]
        restore = f"\x1b[{self.row + 1};{self.col + 1}H\x1b[m" + "".join(self.style)
        return ("\x1b[m" + "".join(updates) + restore).encode()


def _winsize(fd):
    return fcntl.ioctl(fd, termios.TIOCGWINSZ, bytes(8))


def _cursor_position(input_fd, output):
    output.write(b"\x1b[6n")
    output.flush()
    pending = bytearray()
    deadline = time.monotonic() + 1
    while (remaining := deadline - time.monotonic()) > 0:
        if not select.select([input_fd], [], [], remaining)[0]:
            break
        chunk = os.read(input_fd, 4096)
        if not chunk:
            break
        pending.extend(chunk)
        if match := _CURSOR_REPLY.search(pending):
            row, col = (int(n) - 1 for n in match.groups())
            keys = bytes(pending[:match.start()] + pending[match.end():])
            return row, col, keys
        if len(pending) > 65536:
            break
    raise ValueError("This terminal did not report its cursor position for the animated logo.")


def _shell_command(directory):
    preferred = os.environ.get("SHELL") or pwd.getpwuid(os.getuid()).pw_shell
    shell = shutil.which(preferred or "") or shutil.which("bash") or "/bin/sh"
    if Path(shell).name != "bash":
        return [shell, "-i"]
    # This temporary rc preserves the user's Bash startup. Only an unadorned
    # startup fastfetch call is skipped because the panel is already visible.
    startup = Path(directory) / "bashrc"
    startup.write_text(
        'fastfetch() { if (( $# )); then command fastfetch "$@"; fi; }\n'
        '_playbash_fastfetch_function=$(declare -f fastfetch)\n'
        'if [[ -r ~/.bashrc ]]; then source ~/.bashrc; fi\n'
        'if [[ $(declare -f fastfetch) == "$_playbash_fastfetch_function" ]]; then\n'
        '    if [[ -x "$HOME/.local/bin/fastfetch" ]]; then\n'
        f'        {BASH_FASTFETCH_FUNCTION}'
        '    else\n'
        '        unset -f fastfetch\n'
        '    fi\n'
        'fi\n'
        'unset _playbash_fastfetch_function\n'
        f'export {READY_ENV}=1\n'
    )
    return [shell, "--rcfile", str(startup), "-i"]


def _start_shell(argv, geometry, tty_settings, control_path):
    pid, master = pty.fork()
    if pid == 0:
        try:
            fcntl.ioctl(0, termios.TIOCSWINSZ, geometry)
            termios.tcsetattr(0, termios.TCSANOW, tty_settings)
            env = dict(os.environ, **{CONTROL_ENV: control_path})
            env.pop(READY_ENV, None)
            os.execvpe(argv[0], argv, env)
        except Exception as error:
            os.write(2, f"playbash: could not start the shell: {error}\n".encode())
        os._exit(127)
    return pid, master


def _read_shell(master):
    try:
        return os.read(master, 65536)
    except BlockingIOError:
        return None
    except OSError as error:
        if error.errno != errno.EIO:
            raise
        return b""


def _paint(viewport, animation, graphics, index):
    index %= len(animation.frames)
    if graphics:
        return graphics.paint(viewport, index)
    return viewport.paint(animation.frame(index, encode=ansi_lines))


def _confirmation_input(animation, keys, adjust):
    """Return the Enter decision and preserve input that belongs to the shell."""
    changed = False
    while keys:
        first = keys[:1]
        if first in (b"\r", b"\n"):
            return b"", keys[1:], changed, True
        if first == b"\x03":
            return b"", keys[1:], changed, False
        if first in (b"q", b"Q"):
            raise PlaybackStopped
        if first == b"\x1b":
            command = _KEY_ESCAPE.match(keys)
            if command is None:
                if len(keys) <= 32 and _KEY_PREFIX.fullmatch(keys):
                    break
                keys = keys[1:]
                continue
            if command[0] == b"\x1b[200~":
                return b"", keys, changed, False  # Let the shell process the paste.
            keys = keys[command.end():]
            if command[0] == b"\x1bOM":
                return b"", keys, changed, True
            action = _ARROWS.get(command[1])
            if command[0].startswith(b"\x1bO"):
                action = _KEYPAD_ZOOM.get(command[1], action)
        else:
            action = _ZOOM_KEYS.get(first)
            keys = keys[1:]
        if adjust and action is not None:
            animation.adjust(action)
            changed = True
    return keys, None, changed, False


def confirm_native_logo(save):
    """Wait for confirmation while Kitty's own animation keeps playing."""
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGTERM, interrupt)
    try:
        tty.setcbreak(fd, termios.TCSANOW)
        keys = b""
        while chunk := os.read(fd, 1):
            keys, handoff, _, confirmed = _confirmation_input(None, keys + chunk, False)
            if handoff is not None:
                if confirmed:
                    save()
                break
    except KeyboardInterrupt:
        return
    finally:
        termios.tcsetattr(fd, termios.TCSANOW, original)
        signal.signal(signal.SIGTERM, old_handler)


def _relay(input_fd, output, pid, master, control, viewport, animation, geometry, keys, graphics, adjusting, save):
    os.set_blocking(master, False)
    confirming = adjusting or save is not None
    pending = bytearray() if confirming else bytearray(keys)
    confirmation_keys = keys if confirming else b""
    gap = animation.gap_ms / 1000
    frame = 1
    deadline = time.monotonic() + gap
    stopped = False
    while True:
        if (size := _winsize(input_fd)) != geometry:
            if graphics and viewport.active and viewport.control_ready():
                output.write(graphics.clear())
                output.flush()
            fcntl.ioctl(master, termios.TIOCSWINSZ, size)
            geometry = size
            viewport.active = False
        animating = viewport.active and not stopped
        timeout = min(0.25, max(0, deadline - time.monotonic())) if animating else 0.25
        readers = [master, control]
        if len(pending) < 65536:
            readers.append(input_fd)
        ready, writable, _ = select.select(readers, [master] if pending else [], [], timeout)
        if master in ready:
            data = _read_shell(master)
            if data == b"":
                break
            if data:
                can_erase = graphics and viewport.active and viewport.control_ready()
                viewport.feed(data)
                if can_erase and not viewport.active:
                    output.write(graphics.clear())
                output.write(data)
                output.flush()
        if os.waitpid(pid, os.WNOHANG)[0]:
            break
        if not viewport.active or stopped:
            confirming = False
            confirmation_keys = b""
        if input_fd in ready:
            keys = os.read(input_fd, 4096)
            if not keys:
                break
            if confirming:
                confirmation_keys += keys
            else:
                pending.extend(keys)
        changed = False
        if confirming and confirmation_keys:
            try:
                confirmation_keys, handoff, changed, confirmed = _confirmation_input(animation, confirmation_keys, adjusting)
            except PlaybackStopped:
                if not graphics:
                    blank = (" " * viewport.layout.logo.columns,) * viewport.layout.logo.rows
                    output.write(viewport.paint(blank))
                    output.flush()
                return
            if handoff is not None:
                confirming = False
                pending.extend(handoff)
                if confirmed and save is not None:
                    save()
        if writable:
            try:
                del pending[:os.write(master, pending)]
            except BlockingIOError:
                pass
        if control in ready and control.recv(64) == b"stop":
            if graphics:
                if viewport.control_ready():
                    output.write(graphics.clear())
            else:
                blank = (" " * viewport.layout.logo.columns,) * viewport.layout.logo.rows
                output.write(viewport.paint(blank))
            output.flush()
            stopped = True
        if (stopped or not viewport.active) and animation.frames:
            animation.release_frames()
            if graphics:
                graphics.release_frames()
        advance = time.monotonic() >= deadline
        if animating and viewport.active and not stopped and (advance or changed):
            if advance:
                # Schedule from the frame's start, so rasterization and PTY
                # writes use part of its time slot instead of extending it.
                deadline = time.monotonic() + gap
            if viewport.visible_rows() is not None:
                output.write(_paint(viewport, animation, graphics, frame if advance else frame - 1))
                output.flush()
            if advance:
                frame += 1


def _finish_shell(pid, master):
    os.close(master)
    # Closing the PTY normally hangs up the owned shell. Reap it even when
    # startup failed or the outer process was interrupted.
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        try:
            if os.waitpid(pid, os.WNOHANG)[0]:
                return
        except ChildProcessError:
            return
        time.sleep(0.02)
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)


def stop_logo_shell():
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as control:
        try:
            control.sendto(b"stop", os.environ[CONTROL_ENV])
        except OSError as error:
            raise ValueError("The PlayBash logo session is no longer running.") from error


def run_logo_shell(layout, animation, grid, graphics=None, *, adjust=False, color=False, save=None):
    input_fd = sys.stdin.fileno()
    output = sys.stdout.buffer
    geometry = _winsize(input_fd)
    if struct.unpack("HHHH", geometry) != (grid.rows, grid.columns, grid.pixel_width, grid.pixel_height):
        raise ValueError("Terminal size changed while preparing the logo. Run the command again.")
    original = termios.tcgetattr(input_fd)
    pid = master = None
    viewport = None

    def interrupt(_signum, _frame):
        raise KeyboardInterrupt

    old_handler = signal.signal(signal.SIGTERM, interrupt)
    try:
        with tempfile.TemporaryDirectory(prefix="playbash-logo-") as directory, \
             socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as control:
            path = str(Path(directory) / "stop")
            control.bind(path)
            argv = _shell_command(directory)
            tty.setraw(input_fd, termios.TCSANOW)
            if adjust or save is not None:
                if graphics:
                    output.write(graphics.clear())
                message = b"Arrows move. +/- zoom. " if adjust else b""
                prompt = b"Enter saves. q quits." if save is not None else b"Enter opens the shell. q quits."
                output.write(b"\r" + message + prompt + b"\r\n")
            output.write(b"\r" + layout.output.replace(b"\n", b"\r\n") + b"\x1b[m")
            row, col, keys = _cursor_position(input_fd, output)
            if not (0 <= col < grid.columns and layout.rows_above_cursor <= row < grid.rows):
                raise ValueError("The Fastfetch logo could not be located without changing the terminal.")
            viewport = LogoViewport(layout, grid, row, col)
            output.write(_paint(viewport, animation, graphics, 0))
            output.flush()
            pid, master = _start_shell(argv, geometry, original, path)
            _relay(input_fd, output, pid, master, control, viewport, animation, geometry, keys, graphics, adjust, save)
    finally:
        try:
            animation.release_frames()
            if graphics:
                graphics.release_frames()
            if viewport is not None and viewport.alternate:
                output.write(b"\x1b[?1049l")
                output.flush()
            if viewport is not None and graphics:
                output.write(graphics.clear())
                output.flush()
            elif viewport is not None and color:
                output.write(RESET_FOREGROUND.encode())
                output.flush()
            if pid is not None:
                _finish_shell(pid, master)
        finally:
            termios.tcsetattr(input_fd, termios.TCSANOW, original)
            signal.signal(signal.SIGTERM, old_handler)
