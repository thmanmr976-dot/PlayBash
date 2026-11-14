from dataclasses import dataclass
import sys


RESET_FOREGROUND = "\x1b[39m"


@dataclass(frozen=True)
class ColoredFrame:
    lines: tuple[str, ...]
    colors: bytes  # One RGB triplet per glyph, in row order.


def ansi_lines(frame):
    if not isinstance(frame, ColoredFrame):
        return frame
    stride = len(frame.lines[0]) * 3
    return tuple(_color_text(row, frame.colors[start:start + stride])
                 for row, start in zip(frame.lines, range(0, len(frame.colors), stride)))


def _color_text(text, colors):
    parts = []
    foreground = None
    offset = 0
    for symbol in text:
        if symbol != " ":
            color = colors[offset:offset + 3]
            if color != foreground:
                red, green, blue = color
                parts.append(f"\x1b[38;2;{red};{green};{blue}m")
                foreground = color
        parts.append(symbol)
        offset += 3
    if foreground is not None:
        parts.append(RESET_FOREGROUND)
    return "".join(parts)


def _color_row(text, colors, previous_text, previous_colors, row, foreground):
    # Compare exact RGB only where it affects visible glyphs.
    parts = []
    cursor = -1
    for column, new, color in _changed_cells(text, colors, previous_text, previous_colors):
        if cursor == -1:
            parts.append(f"\x1b[{row};{column + 1}H")
        elif column != cursor:
            # Jump over unchanged cells, even when their colors differ.
            distance = column - cursor
            parts.append("\x1b[C" if distance == 1 else f"\x1b[{distance}C")
        if color is not None and color != foreground:
            red, green, blue = color
            parts.append(f"\x1b[38;2;{red};{green};{blue}m")
            foreground = color
        parts.append(new)
        cursor = column + 1
    return "".join(parts), foreground


def _changed_cells(text, colors, previous_text, previous_colors):
    import numpy as np

    encoding, dtype = ("ascii", "u1") if text.isascii() and previous_text.isascii() else ("utf-32-le", "<u4")
    current = np.frombuffer(text.encode(encoding), dtype=dtype)
    previous = np.frombuffer(previous_text.encode(encoding), dtype=dtype)
    rgb = np.frombuffer(colors, dtype="V3")
    previous_rgb = np.frombuffer(previous_colors, dtype="V3")
    # Treat each RGB triplet as one value. The color of a space is invisible.
    changed = (current != previous) | ((current != ord(" ")) & (rgb != previous_rgb))
    for column in np.flatnonzero(changed).tolist():
        symbol = text[column]
        start = column * 3
        yield column, symbol, colors[start:start + 3] if symbol != " " else None


class ColorRenderer:
    """Keep the terminal's previous video frame so unchanged rows can stay put."""

    def __init__(self, output):
        self.output = output
        self.previous = None

    def render(self, frame):
        previous = self.previous
        self.previous = frame
        width = len(frame.lines[0])
        prompt_row = f"\x1b[{len(frame.lines) + 1};1H"
        if previous is None or (len(previous.lines), len(previous.lines[0])) != (len(frame.lines), width):
            # Resizing can reflow old lines outside the new video rectangle.
            clear_screen = "\x1b[2J" if previous is not None else ""
            self.output.write(clear_screen + "\x1b[H" + "\n".join(ansi_lines(frame)) + prompt_row)
            self.output.flush()
            return
        stride = width * 3
        changes = []
        foreground = None
        for i, (text, before) in enumerate(zip(frame.lines, previous.lines)):
            offset = i * stride
            colors = frame.colors[offset:offset + stride]
            old_colors = previous.colors[offset:offset + stride]
            if text != before or (text.strip() and colors != old_colors):
                update, foreground = _color_row(text, colors, before, old_colors, i + 1, foreground)
                changes.append(update)
        update = "".join(changes)
        if update:
            reset = RESET_FOREGROUND if foreground is not None else ""
            self.output.write(update + reset + prompt_row)
            self.output.flush()


def clear():
    sys.stdout.write("\033[2J")
    sys.stdout.flush()


def home():
    sys.stdout.write("\033[H")


def hide_cursor():
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()


def show_cursor():
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def reset_foreground():
    sys.stdout.write(RESET_FOREGROUND)
    sys.stdout.flush()


def render(frame):

    home()

    sys.stdout.write("\n".join(ansi_lines(frame)))

    sys.stdout.flush()
