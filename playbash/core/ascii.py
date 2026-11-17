import cv2

from playbash.core.charset import BASE_CHARSETS, BLOCK_SHADES, EDGE_STROKES
from playbash.core.glyphs import render_ascii_shapes, render_ordered_palette


def frame_to_ascii(frame, width, height, mode):
    # Global contrast can clip hair and shadows before they reach the renderer.
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    return gray_to_ascii(gray, width, height, mode)


def gray_to_ascii(gray, width, height, mode):
    palette = BASE_CHARSETS[mode]
    strokes = EDGE_STROKES.get(mode, "")
    if mode in ("classic", "dense"):
        return render_ascii_shapes(gray, width, height, palette, strokes=strokes)
    if mode == "blocks":
        return render_ordered_palette(gray, width, height, BLOCK_SHADES, block_shapes=True)
    return render_ordered_palette(gray, width, height, palette, strokes=strokes)


def cell_colors(frame, width, height, *, bgr=False):
    """Sample the foreground color for each glyph from the same cropped frame."""
    colors = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
    if colors.ndim == 2 or colors.shape[2] == 1:
        colors = cv2.cvtColor(colors, cv2.COLOR_GRAY2RGB)
    else:
        colors = colors[:, :, :3]
        if bgr:
            colors = colors[:, :, ::-1]
    # Lift near-black strokes so the glyphs that represent shadows stay visible.
    red, green, blue = colors.transpose(2, 0, 1)
    peak = cv2.max(cv2.max(red, green), blue)
    lift = cv2.subtract(96, peak)
    return colors + lift[:, :, None]
