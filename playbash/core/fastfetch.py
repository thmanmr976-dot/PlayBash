"""Keep a looping PlayBash logo in the current Fastfetch layout."""
import base64
from dataclasses import dataclass
import errno
import fcntl
import math
import os
from pathlib import Path
import pty
import re
import secrets
import select
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unicodedata
import zlib

from playbash.core.logo_default import CONTROL_ENV, load_default_logo, native_fastfetch, save_default_logo
from playbash.core.logo_shell import confirm_native_logo, run_logo_shell, stop_logo_shell
from playbash.core.input import PlaybackStopped
from playbash.core.renderer import ansi_lines
from playbash.settings import load as load_settings


IMAGE_ID = 0x50424C47
CHUNK_SIZE = 3072  # Leave room for the header in a terminal APC buffer.
KONSOLE_PLACEMENT_ID = 1
PIXEL_FORMAT = 32  # The graphics payload contains four RGBA bytes per pixel.
_GRAPHICS = re.compile(rb"\x1b_G([^;\x1b]*);[^\x1b]*\x1b\\")
_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


@dataclass(frozen=True)
class Grid:
    columns: int
    rows: int
    pixel_width: int
    pixel_height: int

    @classmethod
    def current(cls):
        rows, cols, width, height = struct.unpack(
            "HHHH", fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, bytes(8))
        )
        if not rows or not cols:
            raise ValueError("Could not read the terminal size.")
        return cls(cols, rows, width, height)


@dataclass(frozen=True)
class Logo:
    columns: int
    rows: int


@dataclass(frozen=True)
class Layout:
    output: bytes
    column: int
    rows_above_cursor: int
    logo: Logo


def _fastfetch_output(executable, grid, args):
    """Capture Fastfetch in a private PTY with the real grid, without forwarding queries."""
    master, slave = pty.openpty()
    process = None
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack(
            "HHHH", grid.rows, grid.columns, grid.pixel_width, grid.pixel_height
        ))
        process = subprocess.Popen(
            [executable, "--pipe", "false", *args],
            stdin=subprocess.DEVNULL, stdout=slave, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        os.close(slave)
        slave = None
        output = bytearray()
        deadline = time.monotonic() + 10
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([master], [], [], remaining)[0]:
                raise ValueError("Fastfetch did not finish measuring the logo.")
            try:
                part = os.read(master, 65536)
            except OSError as error:
                if error.errno != errno.EIO:
                    raise
                break
            if not part:
                break
            output.extend(part)
            if len(output) > 8 * 1024 * 1024:
                raise ValueError("Fastfetch's logo output is too large to measure.")
        if process.wait(timeout=max(0.1, deadline - time.monotonic())):
            raise ValueError("Fastfetch could not render its configured layout.")
        return bytes(output).replace(b"\r\n", b"\n")
    except subprocess.TimeoutExpired as error:
        raise ValueError("Fastfetch did not finish rendering its layout.") from error
    finally:
        if slave is not None:
            os.close(slave)
        os.close(master)
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()


def _text_width(text):
    width = 0
    for ch in text:
        category = unicodedata.category(ch)
        if category in ("Cc", "Cf", "Mn", "Me") or unicodedata.combining(ch):
            continue
        width += 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
    return width


def measure_logo(output, grid):
    # Image logos report either a placement in cells or the original raster
    # extent. Fastfetch rounds the raster extent up to whole cells.
    for command in _GRAPHICS.finditer(output):
        values = dict(field.split(b"=", 1) for field in command[1].split(b",") if b"=" in field)
        if values.get(b"a") not in (b"T", b"p"):
            continue
        if b"c" in values and b"r" in values:
            return Logo(int(values[b"c"]), int(values[b"r"]))
        if b"s" in values and b"v" in values and grid.pixel_width and grid.pixel_height:
            return Logo(
                math.ceil(int(values[b"s"]) * grid.columns / grid.pixel_width),
                math.ceil(int(values[b"v"]) * grid.rows / grid.pixel_height),
            )
        raise ValueError("Fastfetch's image logo did not report its dimensions.")
    try:
        text = _ESCAPE.sub("", output.decode("utf-8")).rstrip("\r\n")
    except UnicodeError as error:
        raise ValueError("Fastfetch's configured logo could not be measured.") from error
    if "\x1b" in text or not text.strip():
        raise ValueError("Fastfetch has no measurable logo. Enable a text or Kitty image logo.")
    lines = text.split("\n")
    return Logo(max(map(_text_width, lines)), len(lines))


def _line_position(line, columns, marker):
    """Follow Fastfetch's horizontal cursor moves (used by right-side logos)."""
    column = 0
    anchor = None
    offset = 0
    for escape in [*_ESCAPE.finditer(line), None]:
        end = escape.start() if escape else len(line)
        text = line[offset:end]
        if marker in text and anchor is None:
            anchor = column + _text_width(text.split(marker, 1)[0])
        column += _text_width(text)
        if column > columns:
            raise ValueError("Fastfetch's layout is wider than this terminal.")
        if escape is None:
            break
        control = escape[0]
        cursor = re.fullmatch(r"\x1b\[(\d*)([CDG])", control)
        if cursor:
            count = max(1, int(cursor[1] or 1))
            if cursor[2] == "G":
                column = min(columns - 1, count - 1)
            elif cursor[2] == "C":
                column = min(columns - 1, column + count)
            else:
                column = max(0, column - count)
        offset = escape.end()
    return anchor


def prepare_layout(output, marker, logo, grid):
    lines = output.decode("utf-8", errors="strict").split("\n")
    if _ESCAPE.sub("", lines[-1]):
        lines.append("")
    placements = []
    for index, line in enumerate(lines):
        anchor = _line_position(line, grid.columns, marker)
        if anchor is not None:
            if line.count(marker) != logo.columns:
                raise ValueError("Could not identify Fastfetch's reserved logo cells.")
            placements.append((index, anchor))
    if not placements:
        raise ValueError("Fastfetch did not reserve space for its logo.")
    row, column = placements[0]
    height = len(placements)
    if placements != [(row + i, column) for i in range(height)]:
        raise ValueError("Fastfetch's logo area is not rectangular.")
    if len(lines) > grid.rows or column + logo.columns > grid.columns:
        raise ValueError("Fastfetch's layout does not fit this terminal at its current size.")
    return Layout(
        "\n".join(lines).replace(marker, " ").encode(),
        column, len(lines) - 1 - row, Logo(logo.columns, height),
    )


def _get_layout(executable, grid):
    original = _fastfetch_output(executable, grid, [
        "--structure", ":", "--logo-padding", "0", "--logo-padding-top", "0",
        "--logo-position", "left", "--logo-print-remaining", "true",
    ])
    logo = measure_logo(original, grid)
    if not 0 < logo.columns < grid.columns or not 0 < logo.rows < grid.rows:
        raise ValueError("Fastfetch's configured logo does not fit this terminal.")
    # Private-use characters occupy one cell and are only sent to the probe.
    # Replace them with spaces before the layout reaches the terminal.
    marker = chr(0xF0000 + secrets.randbelow(65534))
    placeholder = "\n".join([marker * logo.columns] * logo.rows)
    output = _fastfetch_output(executable, grid, ["--data-raw", placeholder])
    return prepare_layout(output, marker, logo, grid)


def _graphics(command):
    return f"\x1b_G{command}\x1b\\".encode("ascii")


def _encode_pixels(data):
    return zlib.compress(data, level=1)


def _image_commands(compressed, params, continuation=b"q=2"):
    encoded = base64.b64encode(compressed)
    commands = bytearray()
    for offset in range(0, len(encoded), CHUNK_SIZE):
        header = params if not offset else continuation
        more = b"1" if offset + CHUNK_SIZE < len(encoded) else b"0"
        commands.extend(b"\x1b_G" + header + b",m=" + more + b";"
                        + encoded[offset:offset + CHUNK_SIZE] + b"\x1b\\")
    return bytes(commands)


def _send_frame(output, encoded, width, height, gap, first):
    action = "t" if first else "f"
    params = f"a={action},i={IMAGE_ID},f={PIXEL_FORMAT},o=z,s={width},v={height},q=2"
    if not first:
        params += f",X=1,z={gap}"
    continuation = b"q=2" if first else b"a=f,q=2"
    output.write(_image_commands(encoded, params.encode(), continuation))


def _raster_frames(frames, raster):
    previous = None
    for frame in frames:
        if frame != previous:
            encoded = _encode_pixels(raster.pixels(frame))
            previous = frame
        yield encoded


def _in_konsole():
    return bool(os.environ.get("KONSOLE_VERSION") or os.environ.get("KONSOLE_DBUS_SESSION"))


def _in_kitty():
    return ((os.environ.get("TERM") == "xterm-kitty"
             or (os.environ.get("KITTY_WINDOW_ID") and not _in_konsole()))
            and not (os.environ.get("TMUX") or os.environ.get("STY")))


def _delete_logo():
    return _graphics(f"a=d,d=I,i={IMAGE_ID},q=2")


class RasterLogo:
    """Replace one graphics placement as the video plays or the framing changes."""

    def __init__(self, layout, animation, grid, mode, *, adjust=False):
        from playbash.core.logo_video import GlyphRaster, raster_size

        self.logo = layout.logo
        self.width, self.height = raster_size(self.logo, grid)
        self.animation = animation
        self.raster = GlyphRaster(mode, (self.width, self.height))
        self.encoded = None if adjust else tuple(_raster_frames(animation.frames, self.raster))

    def _encode(self, frame):
        return _encode_pixels(self.raster.pixels(frame))

    def paint(self, viewport, index):
        visible = viewport.visible_rows()
        if visible is None:
            return b""
        first, end = visible
        crop_y = self.height * first // self.logo.rows
        crop_height = self.height * end // self.logo.rows - crop_y
        if crop_height < 1:
            return b""
        # C=1 keeps the graphics command from moving the cursor. An explicit
        # placement ID replaces the previous frame rather than stacking images.
        params = (
            f"a=T,i={IMAGE_ID},p={KONSOLE_PLACEMENT_ID},f={PIXEL_FORMAT},o=z,s={self.width},v={self.height},"
            f"c={self.logo.columns},r={end - first},C=1,q=2,w={self.width},y={crop_y},h={crop_height}"
        )
        start = f"\x1b[{viewport.top + first + 1};{viewport.layout.column + 1}H"
        restore = f"\x1b[{viewport.row + 1};{viewport.col + 1}H"
        if self.encoded is None:
            frame = self.animation.frame(index, encode=self._encode)
        else:
            frame = self.encoded[index]
        return start.encode() + _image_commands(frame, params.encode()) + restore.encode()

    def clear(self):
        return _delete_logo()

    def release_frames(self):
        self.encoded = None


def _display_kitty(layout, animation, grid, mode, *, save=None):
    from playbash.core.logo_video import GlyphRaster, raster_size

    width, height = raster_size(layout.logo, grid)
    raster = GlyphRaster(mode, (width, height))
    with tempfile.TemporaryFile() as frames:
        for index, encoded in enumerate(_raster_frames(animation.frames, raster)):
            _send_frame(frames, encoded, width, height, animation.gap_ms, index == 0)
        frames.write(_graphics(f"a=a,i={IMAGE_ID},r=1,z={animation.gap_ms},q=2"))
        if Grid.current() != grid:
            raise ValueError("Terminal size changed while preparing the logo. Run the command again.")
        frames.seek(0)
        output = sys.stdout.buffer
        output.write(_delete_logo())
        shutil.copyfileobj(frames, output)
        if save is not None:
            output.write(b"\rEnter saves the logo. q quits.\r\n")
        output.write(b"\r" + layout.output)
        # Print the panel first so any scrolling happens before placement.
        output.write(
            f"\x1b7\x1b[{layout.rows_above_cursor}A\x1b[{layout.column+1}G".encode()
            + _graphics(f"a=p,i={IMAGE_ID},c={layout.logo.columns},r={layout.logo.rows},C=1,q=2")
            + b"\x1b8"
            + _graphics(f"a=a,i={IMAGE_ID},s=3,v=1,q=2")
        )
        output.flush()
    if save is not None:
        try:
            confirm_native_logo(save)
        except PlaybackStopped:
            output.write(_delete_logo())
            output.flush()


def show_fastfetch(video=None, stop=False, *, adjust=False):
    if stop:
        if os.environ.get(CONTROL_ENV):
            stop_logo_shell()
        if sys.stdout.isatty() and _in_kitty():
            sys.stdout.buffer.write(_delete_logo())
            sys.stdout.buffer.flush()
        elif not os.environ.get(CONTROL_ENV):
            raise ValueError("Run --stop in the terminal session displaying the logo.")
        return
    executable = native_fastfetch()
    if not executable:
        raise ValueError("Fastfetch is not installed or is not on PATH.")
    choose = video is not None
    framing = None
    if not choose:
        selection = load_default_logo()
        if selection is None:
            os.execv(executable, [executable])
        video, framing = selection
    path = Path(video).expanduser().resolve()
    if not path.is_file():
        raise ValueError(f"Video not found: {path}")
    if not all(shutil.which(name) for name in ("ffmpeg", "ffprobe")):
        raise ValueError("Animated logos need ffmpeg and ffprobe on PATH.")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Run animated Fastfetch in an interactive terminal.")
    from playbash.core.logo_video import prepare_video, symbol_scale

    grid = Grid.current()
    layout = _get_layout(executable, grid)
    settings = load_settings()
    mode = settings["mode"]
    color = settings["color"]
    kitty = _in_kitty()
    konsole = _in_konsole() and not (os.environ.get("TMUX") or os.environ.get("STY"))
    scale = symbol_scale(layout.logo, grid) if kitty or konsole else 1
    raster = kitty or (konsole and scale > 1)
    encode = ansi_lines if color and not raster and not adjust else None
    animation = prepare_video(path, layout.logo, grid, mode, scale, adjust=adjust, color=color, encode=encode,
                              framing=framing)

    def save():
        try:
            save_default_logo(path, animation.framing if adjust else None, executable)
        except (OSError, ValueError) as error:
            print(f"playbash: could not save the logo: {error}", file=sys.stderr)

    confirm = save if choose else None
    try:
        if Grid.current() != grid:
            raise ValueError("Terminal size changed while preparing the logo. Run the command again.")
        if os.environ.get(CONTROL_ENV):
            stop_logo_shell()
        if kitty and not adjust:
            _display_kitty(layout, animation, grid, mode, save=confirm)
        else:
            graphics = RasterLogo(layout, animation, grid, mode, adjust=adjust) if raster else None
            run_logo_shell(layout, animation, grid, graphics=graphics, adjust=adjust, color=color, save=confirm)
    finally:
        animation.release_frames()
