from string import ascii_letters, digits, punctuation

BLOCK_SHADES = "█▓▒░ "
# Each bit covers a quadrant in reading order, starting at the top left.
BLOCK_QUADRANTS = " ▘▝▀▖▌▞▛▗▚▐▜▄▙▟█"
BLOCK_SHAPES = BLOCK_QUADRANTS[1:-1]

EDGE_SEGMENTS = {
    "╱": ((0, 1, 1, 0),), "╲": ((0, 0, 1, 1),),
    "─": ((0, .5, 1, .5),), "│": ((.5, 0, .5, 1),),
    "╭": ((.5, 1, .5, .5, 1, .5),), "╮": ((.5, 1, .5, .5, 0, .5),),
    "╰": ((.5, 0, .5, .5, 1, .5),), "╯": ((.5, 0, .5, .5, 0, .5),),
    "╳": ((0, 1, 1, 0), (0, 0, 1, 1)),
}
EDGE_STROKES = {
    "classic": "╱╲─│╭╮╰╯",
    "dense": "".join(EDGE_SEGMENTS),
    "matrix": "╱╲─│╳",
    "hex": "╱╲─│",
    "binary": "╱╲─│",
}

BASE_CHARSETS = {

    "classic":
        "@%#*+=-:_|/\\. ",

    "dense":
        ascii_letters + digits + punctuation + " ",

    "blocks":
        BLOCK_SHADES + BLOCK_SHAPES,

    "matrix":
        "@#01",

    "hex":
        "0123456789ABCDEF",

    "binary":
        "01"

}

CHARSETS = {mode: palette + EDGE_STROKES.get(mode, "") for mode, palette in BASE_CHARSETS.items()}
