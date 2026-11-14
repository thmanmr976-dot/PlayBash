"""Choose ordinary ASCII glyphs using both tone and the shape inside a cell."""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# The 1:2 grid approximates a terminal cell's shape. A cell still produces
# one ASCII character; these samples distinguish e.g. '/' from '\\' or '|'.
_SAMPLE_WIDTH = 3
_SAMPLE_HEIGHT = 6
_SAMPLE_COUNT = _SAMPLE_WIDTH * _SAMPLE_HEIGHT
_NEAR_WHITE = 205
_FLAT_HIGHLIGHT_RANGE = 5


def _ordered_thresholds():
    ranks = np.zeros((1, 1), dtype=np.float32)
    for _ in range(3):
        ranks = np.block([[4 * ranks, 4 * ranks + 2], [4 * ranks + 3, 4 * ranks + 1]])
    return (ranks + 0.5) / ranks.size


_THRESHOLDS = _ordered_thresholds()


@lru_cache(maxsize=6)
def _glyph_tables(palette):
    # Pillow includes a small fixed-width reference font. This is only used
    # to measure shapes; it does not change the user's terminal font.
    bitmap_font = getattr(ImageFont, 'load_default_imagefont', ImageFont.load_default)()
    cell_width, cell_height = bitmap_font.getbbox('M')[2:]
    masks = []
    for symbol in palette:
        glyph = Image.new('L', (cell_width, cell_height))
        ImageDraw.Draw(glyph).text((0, 0), symbol, font=bitmap_font, fill=255)
        samples = glyph.resize((_SAMPLE_WIDTH, _SAMPLE_HEIGHT), Image.Resampling.BOX)
        masks.append(np.asarray(samples, dtype=np.float32).ravel() / 255)
    masks = np.array(masks, dtype=np.float32).reshape(-1, _SAMPLE_HEIGHT, _SAMPLE_WIDTH)
    if '/' in palette and '\\' in palette:
        # Average the two diagonals after mirroring. Font bearings can otherwise
        # make a centered stroke match one direction better than its reflection.
        forward, backward = palette.index('/'), palette.index('\\')
        diagonal = (masks[forward] + masks[backward, :, ::-1]) * 0.5
        masks[forward] = diagonal
        masks[backward] = diagonal[:, ::-1]
    masks = masks.reshape(-1, _SAMPLE_COUNT)
    means = masks.mean(axis=1)
    density = means / means.max()
    shapes = masks - means[:, None]
    norms = np.linalg.norm(shapes, axis=1)
    shapes /= np.maximum(norms, 1e-6)[:, None] * np.sqrt(_SAMPLE_COUNT)
    tone_lookup = np.abs(np.linspace(0, 1, 256)[:, None] - density).argmin(axis=1)
    steps = np.zeros_like(shapes)
    steps[:-1] = shapes[:-1] - shapes[1:]
    return density, np.ascontiguousarray(shapes.T), tone_lookup, steps


@lru_cache(maxsize=6)
def _text_palette(palette):
    if palette.isascii():
        return np.frombuffer(palette.encode('ascii'), dtype=np.uint8), 'ascii'
    return np.frombuffer(palette.encode('utf-32-le'), dtype='V4'), 'utf-32-le'


def _text_lines(palette, indices, width):
    symbols, encoding = _text_palette(palette)
    text = symbols[indices].tobytes().decode(encoding)
    return [text[start:start + width] for start in range(0, len(text), width)]


@lru_cache(maxsize=4)
def _dither_pattern(width, height):
    rows = np.arange(height) % _THRESHOLDS.shape[0]
    cols = np.arange(width) % _THRESHOLDS.shape[1]
    return _THRESHOLDS[rows[:, None], cols].ravel()


def _sample_cells(gray, width, height):
    scaled_width, scaled_height = width * _SAMPLE_WIDTH, height * _SAMPLE_HEIGHT
    if gray.shape != (scaled_height, scaled_width):
        interpolation = cv2.INTER_AREA if scaled_width <= gray.shape[1] else cv2.INTER_CUBIC
        gray = cv2.resize(gray, (scaled_width, scaled_height), interpolation=interpolation)
    patches = gray.reshape(height, _SAMPLE_HEIGHT, width, _SAMPLE_WIDTH).transpose(0, 2, 1, 3)
    return patches.astype(np.float32, order='C').reshape(-1, _SAMPLE_COUNT)


def _contours(patches, means, ranges):
    # Cells below this contrast cannot match a contour. Only calculate the
    # deviation on candidates and reuse their centered samples for scoring.
    edges = ranges >= 12 / 255
    centered = patches[edges]
    centered -= means[edges, None]
    deviations = np.sqrt(np.square(centered).mean(axis=1))
    accepted = (ranges[edges] >= 0.12) | (deviations >= 4 / 255)
    edges[edges] = accepted
    if not accepted.all():
        centered = centered[accepted]
        deviations = deviations[accepted]
    # Amplify only shape, never the mean tone. The fixed noise floor and capped
    # gain avoid turning codec noise into contours or stretching each frame.
    gain = np.clip(0.09 / deviations, 1.0, 2.5)
    centered *= gain[:, None]
    return edges, centered


def render_ascii_shapes(gray, width, height, palette):
    """Use darker source areas for denser glyphs, as in the original modes."""
    patches = _sample_cells(gray, width, height)
    np.subtract(255, patches, out=patches)
    patches /= 255
    means = patches.mean(axis=1)
    density, shapes, tone_lookup, _ = _glyph_tables(palette)
    indices = tone_lookup[np.rint(means * 255).astype(np.uint8)]

    ranges = np.ptp(patches, axis=1)
    edges, centered = _contours(patches, means, ranges)
    if edges.any():
        score = means[edges, None] - density
        np.square(score, out=score)
        score = cv2.gemm(centered, shapes, -0.75, score, 1.0, dst=score)
        indices[edges] = score.argmin(axis=1)
    # Clear flat highlights, including slightly off-white video backgrounds.
    # Keep mixed cells so light contours still have a glyph to represent them.
    if " " in palette:
        flat_highlights = (means <= (255 - _NEAR_WHITE) / 255) & (ranges <= _FLAT_HIGHLIGHT_RANGE / 255)
        indices[flat_highlights] = palette.index(" ")
    return _text_lines(palette, indices, width)


def render_ordered_palette(gray, width, height, palette):
    """Preserve the palette's dark-to-light order while keeping fine edges."""
    patches = _sample_cells(gray, width, height)
    patches /= 255
    means = patches.mean(axis=1)
    luma = means.reshape(height, width)
    local_mean = cv2.GaussianBlur(luma, (3, 3), 0.8)
    detail = luma - local_mean
    # Emphasize small differences between neighboring cells. Limit the boost
    # so high-contrast edges do not produce broad halos.
    boost = np.sign(detail) * np.clip((np.abs(detail) - 2 / 255) * 1.5, 0, 0.10)
    levels = np.clip(luma + boost, 0, 1).ravel() * (len(palette) - 1)

    # Spend the limited tones around contours. Fade the fixed dither pattern
    # to ordinary rounding on flat regions instead of texturing backgrounds.
    pattern = _dither_pattern(width, height)
    ranges = np.ptp(patches, axis=1)
    activity = np.maximum(np.abs(detail).ravel(), ranges * 0.5)
    strength = np.clip((activity - 4 / 255) / (16 / 255), 0, 1)
    threshold = 0.5 + strength * (pattern - 0.5)
    indices = np.floor(levels + threshold).astype(np.intp)

    if palette.isascii():
        edges, centered = _contours(patches, means, ranges)
        if edges.any():
            # A character shape may break a tie between adjacent tones. It
            # cannot exchange a dark digit for a distant bright one.
            _, _, _, steps = _glyph_tables(palette)
            low = np.floor(levels[edges]).astype(np.intp)
            high = np.minimum(low + 1, len(palette) - 1)
            shape_bias = np.sum(centered * steps[low], axis=1)
            fraction = levels[edges] - low
            indices[edges] = np.where(fraction + threshold[edges] + 0.35 * shape_bias >= 1, high, low)

    if " " not in palette:
        palette += " "
    flat_highlights = (means >= _NEAR_WHITE / 255) & (ranges <= _FLAT_HIGHLIGHT_RANGE / 255)
    indices[flat_highlights] = palette.index(" ")
    return _text_lines(palette, indices, width)
