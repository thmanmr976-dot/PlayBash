"""Prepare the same PlayBash text frames for either animated logo backend."""
from contextlib import ExitStack
from dataclasses import dataclass
import json
import math
import subprocess
import sys
import tempfile
import zlib

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from playbash.core.ascii import cell_colors, frame_to_ascii, gray_to_ascii
from playbash.core.charset import BLOCK_QUADRANTS, BLOCK_SHAPES, CHARSETS, EDGE_SEGMENTS
from playbash.core.glyphs import draw_edge_stroke
from playbash.core.renderer import ColoredFrame
from playbash.core.logo_cache import cell_ratio, raster_size, symbol_scale


MAX_FRAME_BYTES = 256 * 1024 * 1024
MAX_RENDER_CACHE_BYTES = 48 * 1024 * 1024
COLOR_SPOOL_BYTES = 32 * 1024 * 1024
RASTER_CHANNELS = 4
MIN_CENTER_ZOOM = 1.12
ZOOM_STEP = 1.15
PAN_STEP = 0.08
PAN_DIRECTIONS = {"up": (0, -1), "down": (0, 1), "right": (1, 0), "left": (-1, 0)}


@dataclass
class LogoAnimation:
    frames: tuple
    gap_ms: int

    def frame(self, index, *, encode=None):
        frame = self.frames[index]
        return encode(frame) if encode is not None else frame

    def release_frames(self):
        self.frames = ()


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    aspect: float
    duration: float


def _video_info(video):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "V:0",
             "-show_entries", "stream=width,height,sample_aspect_ratio:format=duration",
             "-of", "json", str(video)],
            check=True, capture_output=True, timeout=10,
        )
        data = json.loads(result.stdout)
        stream = data["streams"][0]
        width, height = int(stream["width"]), int(stream["height"])
        aspect = width / height
    except (subprocess.SubprocessError, ValueError, KeyError, IndexError, ZeroDivisionError) as error:
        raise ValueError(f"Could not read a video stream from: {video}") from error
    try:
        horizontal, vertical = map(int, stream.get("sample_aspect_ratio", "").split(":"))
        if horizontal > 0 and vertical > 0:
            aspect *= horizontal / vertical
    except ValueError:
        pass
    try:
        duration = float(data.get("format", {}).get("duration", 0))
    except (ValueError, TypeError):
        duration = 0
    return VideoInfo(width, height, aspect, duration)


def _cover_dimensions(source_aspect, target_aspect):
    # Filling the logo already zooms wide or tall clips. Only add a small
    # zoom when the source aspect is already close to the logo's aspect.
    width = max(1.0, source_aspect / target_aspect)
    height = max(1.0, target_aspect / source_aspect)
    extra_zoom = max(1.0, MIN_CENTER_ZOOM / max(width, height))
    return width * extra_zoom, height * extra_zoom


def _center_crop(cover):
    width, height = cover
    return (
        f"crop=w='max(1,trunc(iw*{1 / width:.12f}))':"
        f"h='max(1,trunc(ih*{1 / height:.12f}))':x=(iw-ow)/2:y=(ih-oh)/2:exact=1"
    )


def _visible_axis(cells, pixels, extent, offset):
    start = (1 - extent) / 2 + offset
    first = min(cells - 1, max(0, round(start * cells)))
    end = min(cells, max(first + 1, round((start + extent) * cells)))
    first_pixel = min(pixels - 1, max(0, round((first / cells - start) * pixels / extent)))
    end_pixel = min(pixels, max(first_pixel + 1, round((end / cells - start) * pixels / extent)))
    return first, end, slice(first_pixel, end_pixel)


def _clamp_offset(offset, extent):
    # Let the user pan past the edge slightly, while keeping the video visible.
    limit = abs(1 - extent) / 2 + 0.2 * min(1, extent)
    return max(-limit, min(limit, offset))


class AdjustableAnimation:
    """Crop the decoded source before rendering glyphs for the current view."""

    def __init__(self, frames, gap_ms, columns, rows, cover, mode, source_shape, source_file=None, *, framing=None):
        self.frames = frames
        self.gap_ms = gap_ms
        self.columns = columns
        self.rows = rows
        self.cover = cover
        self.mode = mode
        self.source_shape = source_shape
        self.sample_bytes = math.prod(source_shape)
        self.source_file = source_file
        self.zoom, self.x, self.y = framing if framing is not None else (1.0, 0.0, 0.0)
        self.x = _clamp_offset(self.x, self.cover[0] * self.zoom)
        self.y = _clamp_offset(self.y, self.cover[1] * self.zoom)
        self._rendered = {}
        self._cache_bytes = 0
        self._render_file = None
        self._spill_enabled = source_file is not None
        source_bytes = sum(map(len, frames)) if source_file is None else COLOR_SPOOL_BYTES
        self._cache_limit = min(MAX_RENDER_CACHE_BYTES, MAX_FRAME_BYTES - source_bytes)

    @property
    def framing(self):
        return self.zoom, self.x, self.y

    def adjust(self, key):
        before = self.framing
        if key in ("+", "-"):
            factor = ZOOM_STEP if key == "+" else 1 / ZOOM_STEP
            zoom = min(3.0, max(0.85 / max(self.cover), self.zoom * factor))
            # Keep the current point of interest under the center of the logo.
            self.x *= zoom / self.zoom
            self.y *= zoom / self.zoom
            self.zoom = zoom
        else:
            dx, dy = PAN_DIRECTIONS[key]
            self.x += dx * max(PAN_STEP, 1 / self.columns)
            self.y += dy * max(PAN_STEP, 1 / self.rows)
        self.x = _clamp_offset(self.x, self.cover[0] * self.zoom)
        self.y = _clamp_offset(self.y, self.cover[1] * self.zoom)
        if before != self.framing:
            self._clear_render_cache()

    def _clear_render_cache(self):
        self._rendered.clear()
        self._cache_bytes = 0
        if self._render_file is not None:
            self._render_file.close()
            self._render_file = None
        self._spill_enabled = self.source_file is not None

    def release_frames(self):
        self.frames = ()
        self._clear_render_cache()
        if self.source_file is not None:
            self.source_file.close()
            self.source_file = None

    def frame(self, index, *, encode=None):
        # The encoded form is cached on graphical terminals, so later loops
        # can reuse the packet payload without rasterizing or compressing it.
        key = (self.frames[index], encode)
        frame = self._rendered.get(key)
        if isinstance(frame, _CachedPayload):
            self._render_file.seek(frame.offset)
            return self._render_file.read(frame.size)
        if frame is not None:
            return frame
        frame = self._render_frame(index)
        if encode is not None:
            frame = encode(frame)
        size = sys.getsizeof(frame)
        if isinstance(frame, ColoredFrame):
            size += sys.getsizeof(frame.colors) + sys.getsizeof(frame.lines)
            size += sum(map(sys.getsizeof, frame.lines))
        elif isinstance(frame, (tuple, list)):
            size += sum(map(sys.getsizeof, frame))
        if self._cache_bytes + size <= self._cache_limit:
            self._rendered[key] = frame
            self._cache_bytes += size
        elif self._spill_enabled and isinstance(frame, bytes):
            self._spill_frame(key, frame)
        return frame

    def _spill_frame(self, key, frame):
        # Cache compressed graphics on long clips without growing the RAM budget.
        try:
            if self._render_file is None:
                self._render_file = tempfile.TemporaryFile(buffering=0)
            cache = self._render_file
            offset = cache.seek(0, 2)
            if offset + len(frame) <= MAX_FRAME_BYTES and cache.write(frame) == len(frame):
                self._rendered[key] = _CachedPayload(offset, len(frame))
                return
        except OSError:
            pass  # Playback can still render uncached frames.
        self._spill_enabled = False

    def _render_frame(self, index):
        data = self.frames[index]
        if self.source_file is not None:
            offset, size = data
            self.source_file.seek(offset)
            data = self.source_file.read(size)
        if len(data) < self.sample_bytes:
            data = zlib.decompress(data)
        source = np.frombuffer(data, dtype=np.uint8).reshape(self.source_shape)
        return self.render_source(source)

    def render_source(self, source):
        height, width = source.shape[:2]
        left, right, x = _visible_axis(self.columns, width, self.cover[0] * self.zoom, self.x)
        top, bottom, y = _visible_axis(self.rows, height, self.cover[1] * self.zoom, self.y)
        width, height = right - left, bottom - top
        crop = source[y, x]
        to_ascii = gray_to_ascii if crop.ndim == 2 else frame_to_ascii
        symbols = to_ascii(crop, width, height, self.mode)
        lines = [" " * self.columns] * self.rows
        lines[top:bottom] = [" " * left + line + " " * (self.columns - right) for line in symbols]
        if crop.ndim == 2:
            return tuple(lines)
        colors = cell_colors(crop, width, height)
        if (width, height) != (self.columns, self.rows):
            padded = np.zeros((self.rows, self.columns, 3), dtype=np.uint8)
            padded[top:bottom, left:right] = colors
            colors = padded
        return ColoredFrame(tuple(lines), colors.tobytes())


@dataclass(frozen=True)
class _CachedPayload:
    offset: int
    size: int


def prepare_video(video, logo, grid, mode, scale=1, *, adjust=False, color=False, encode=None, framing=None):
    if mode not in CHARSETS:
        raise ValueError(f"Unknown rendering mode: {mode}")
    info = _video_info(video)
    if info.aspect <= 0:
        raise ValueError("Invalid video dimensions.")
    columns, rows = logo.columns * scale, logo.rows * scale
    width, height = columns * 3, rows * 6
    cover = _cover_dimensions(info.aspect, logo.columns * cell_ratio(grid) / logo.rows)
    use_source = adjust or framing is not None
    if use_source:
        # Retain the edges for panning, and keep additional source samples
        # for zooming without caching the clip at its original resolution.
        width = min(info.width, 1024, round(width * cover[0] * 2))
        height = min(info.height, 1024, round(height * cover[1] * 2))
    if adjust:
        # Keep the grayscale frame rate in color mode. Spill the larger
        # compressed RGB source to a temporary file once the spool fills.
        cache_bytes = width * height
    else:
        raster_width, raster_height = raster_size(logo, grid)
        cache_bytes = raster_width * raster_height * RASTER_CHANNELS
    frame_limit = min(8192, MAX_FRAME_BYTES // cache_bytes)
    fps = 12
    if math.isfinite(info.duration) and info.duration > 0:
        fps = min(fps, (frame_limit - 1) / info.duration)
    if fps < 0.5:
        raise ValueError("This video is too long for a terminal logo; use a shorter clip.")

    filters = [f"fps={fps:.6f}:round=up"]
    if not use_source:
        filters.append(_center_crop(cover))
    filters.append(f"scale={width}:{height}:flags=area")
    gray = use_source and not color
    pixel_format = "gray" if gray else "rgb24"
    source_shape = (height, width) if gray else (height, width, 3)
    frame_size = math.prod(source_shape)
    renderer = None
    if framing is not None and not adjust:
        renderer = AdjustableAnimation((), 0, columns, rows, cover, mode, source_shape, framing=framing)
    frames = []
    previous = None
    with ExitStack() as sources, tempfile.TemporaryFile() as errors:
        source_file = None
        if adjust and color:
            source_file = sources.enter_context(tempfile.SpooledTemporaryFile(max_size=COLOR_SPOOL_BYTES))
        process = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-nostdin", "-noautorotate", "-i", str(video),
             "-map", "0:V:0", "-vf", ",".join(filters), "-an", "-sn", "-dn",
             "-pix_fmt", pixel_format, "-threads", "1", "-f", "rawvideo", "pipe:1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors,
        )
        try:
            while data := process.stdout.read(frame_size):
                if len(data) != frame_size:
                    raise ValueError("FFmpeg returned an incomplete video frame.")
                if len(frames) >= frame_limit:
                    raise ValueError("This video is too long for a terminal logo; use a shorter clip.")
                if data == previous:
                    frames.append(frames[-1])
                    continue
                previous = data
                if adjust:
                    compressed = zlib.compress(data, level=1)
                    stored = compressed if len(compressed) < frame_size else data
                    if source_file is None:
                        frames.append(stored)
                    else:
                        frames.append((source_file.tell(), len(stored)))
                        source_file.write(stored)
                else:
                    rgb = np.frombuffer(data, dtype=np.uint8).reshape(source_shape)
                    if renderer is None:
                        frame = tuple(frame_to_ascii(rgb, columns, rows, mode))
                        if color:
                            frame = ColoredFrame(frame, cell_colors(rgb, columns, rows).tobytes())
                    else:
                        frame = renderer.render_source(rgb)
                    frames.append(encode(frame) if encode is not None else frame)
            if process.wait() or not frames:
                errors.seek(0)
                message = errors.read(512).decode(errors="replace").strip()
                raise ValueError(f"Could not decode the logo video{': ' + message if message else '.'}")
        finally:
            process.stdout.close()
            if process.poll() is None:
                process.kill()
            process.wait()
        gap = round(1000 / fps)
        if adjust:
            animation = AdjustableAnimation(tuple(frames), gap, columns, rows, cover, mode,
                                            source_shape, source_file, framing=framing)
            sources.pop_all()  # The animation owns the spool until playback stops.
            return animation
    return LogoAnimation(tuple(frames), gap)


class GlyphRaster:
    """Rasterize smaller PlayBash glyphs inside the original logo rectangle."""

    def __init__(self, mode, size):
        palette = "".join(dict.fromkeys(CHARSETS[mode] + " "))
        self.indices = str.maketrans(palette, "".join(map(chr, range(len(palette)))))
        font = getattr(ImageFont, "load_default_imagefont", ImageFont.load_default)()
        self.width, self.height = font.getbbox("M")[2:]
        self.size = size
        self.tiles = []
        for symbol in palette:
            if symbol in "█▓▒░":
                # The reference bitmap font contains only ASCII. Use the same
                # solid or shaded coverage for the four block characters.
                coverage = {"█": 4, "▓": 3, "▒": 2, "░": 1}[symbol]
                yy, xx = np.indices((self.height, self.width))
                tile = np.where(((xx + yy * 3) % 4) < coverage, 255, 0).astype(np.uint8)
            elif symbol in EDGE_SEGMENTS:
                tile = np.asarray(draw_edge_stroke(symbol, self.width, self.height))
            elif symbol in BLOCK_SHAPES:
                mask = BLOCK_QUADRANTS.index(symbol)
                y, x = np.indices((self.height, self.width))
                quadrant = (x >= self.width // 2).astype(int) + 2 * (y >= self.height // 2)
                tile = (((mask >> quadrant) & 1) * 255).astype(np.uint8)
            else:
                image = Image.new("L", (self.width, self.height))
                ImageDraw.Draw(image).text((0, 0), symbol, font=font, fill=255)
                tile = np.asarray(image)
            self.tiles.append(tile)
        self.tiles = np.asarray(self.tiles)

    def pixels(self, frame):
        lines, colors = (frame.lines, frame.colors) if isinstance(frame, ColoredFrame) else (frame, None)
        rows, cols = len(lines), len(lines[0])
        indices = np.frombuffer("".join(lines).translate(self.indices).encode("latin-1"), dtype=np.uint8)
        tiles = self.tiles[indices].reshape(rows, cols, self.height, self.width)
        bitmap = tiles.transpose(0, 2, 1, 3).reshape(rows * self.height, cols * self.width)
        # Retain parts of thin strokes when more than one glyph fits in a
        # terminal cell. Nearest-neighbor sampling can drop those strokes.
        alpha = Image.fromarray(bitmap).resize(self.size, Image.Resampling.LANCZOS)
        if colors is not None:
            image = Image.frombytes("RGB", (cols, rows), colors).resize(self.size, Image.Resampling.NEAREST)
        else:
            image = Image.new("RGBA", self.size, (235, 235, 235, 0))
        image.putalpha(alpha)
        return image.tobytes()
