"""Bounded, disposable cache of rendered logo frames, with no decoder imports."""
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile

MAX_CACHE_BYTES = 256 * 1024 * 1024
_MAGIC = b"PLAYBASH-LOGO-1\n"
_LENGTH = struct.Struct("!I")


def cell_ratio(grid):
    if grid.pixel_width and grid.pixel_height:
        return (grid.pixel_width / grid.columns) / (grid.pixel_height / grid.rows)
    return 0.5


def raster_size(logo, grid):
    cell_height = grid.pixel_height / grid.rows if grid.pixel_height else 16
    width = logo.columns * cell_height * cell_ratio(grid)
    height = logo.rows * cell_height
    scale = min(1.0, 512 / max(width, height))
    return max(2, round(width * scale)), max(2, round(height * scale))


def symbol_scale(logo, grid):
    width, height = raster_size(logo, grid)
    return max(1, min(2, width // (logo.columns * 3), height // (logo.rows * 5)))


@dataclass
class CachedLogo:
    frames: tuple
    gap_ms: int
    width: int
    height: int
    raster: bool

    def frame(self, index, *, encode=None):
        frame = self.frames[index]
        if not self.raster:
            frame = tuple(frame.decode("utf-8").split("\n"))
        return encode(frame) if encode is not None else frame

    def release_frames(self):
        self.frames = ()


def cache_path(video, logo, grid, mode, scale, color, framing, raster):
    stat = video.stat()
    source = Path(__file__).parent
    signature = hashlib.sha256()
    for name in ("logo_cache", "logo_video", "ascii", "glyphs", "charset", "renderer", "fastfetch"):
        signature.update((source / (name + ".py")).read_bytes())
    decoder = Path(shutil.which("ffmpeg")).stat()
    key = [
        str(video), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns,
        logo.columns, logo.rows, grid.columns, grid.rows, grid.pixel_width, grid.pixel_height,
        mode, scale, bool(color), framing, raster, signature.hexdigest(), sys.version,
        [version(name) for name in ("numpy", "Pillow", "opencv-python")],
        decoder.st_size, decoder.st_mtime_ns,
    ]
    digest = hashlib.sha256(json.dumps(key, separators=(",", ":")).encode()).hexdigest()
    directory = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "playbash" / "logos"
    return directory / (digest + ".pbl")


def load_cached_logo(path):
    try:
        size = path.stat().st_size
        if size > MAX_CACHE_BYTES:
            return None
        with path.open("rb") as source:
            if source.read(len(_MAGIC)) != _MAGIC:
                return None
            header_size, = _LENGTH.unpack(source.read(_LENGTH.size))
            if header_size > 4096:
                return None
            metadata = json.loads(source.read(header_size))
            gap, width, height, count, raster = metadata
            if (type(raster) is not bool or not all(type(x) is int for x in metadata[:4])
                    or not 1 <= gap <= 2000 or not 1 <= count <= 8192
                    or not 2 <= width <= 512 or not 2 <= height <= 512):
                return None
            frames = []
            checksum = hashlib.sha256()
            for _ in range(count):
                length, = _LENGTH.unpack(source.read(_LENGTH.size))
                if not 0 < length <= size - source.tell():
                    return None
                frame = source.read(length)
                checksum.update(frame)
                if not raster:
                    frame.decode("utf-8")
                frames.append(frames[-1] if frames and frames[-1] == frame else frame)
            if source.read(32) != checksum.digest() or source.read(1):
                return None
        # Touch only complete valid entries for LRU cleanup.
        path.touch()
        return CachedLogo(tuple(frames), gap, width, height, raster)
    except (OSError, ValueError, TypeError, struct.error):
        return None


def save_cached_logo(path, animation):
    metadata = [animation.gap_ms, animation.width, animation.height, len(animation.frames), animation.raster]
    header = json.dumps(metadata).encode()
    size = len(_MAGIC) + _LENGTH.size + len(header) + 32
    size += sum(_LENGTH.size + len(frame) for frame in animation.frames)
    if size > MAX_CACHE_BYTES:
        return
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Keep the whole cache bounded. Atomic replacement lets concurrent
        # shells read either the complete old entry or the complete new one.
        entries = sorted(path.parent.glob("*.pbl"), key=lambda entry: entry.stat().st_mtime_ns)
        total = sum(entry.stat().st_size for entry in entries if entry != path)
        for entry in entries:
            if total + size <= MAX_CACHE_BYTES:
                break
            if entry != path:
                total -= entry.stat().st_size
                entry.unlink(missing_ok=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as target:
            temporary = Path(target.name)
            target.write(_MAGIC)
            target.write(_LENGTH.pack(len(header)))
            target.write(header)
            checksum = hashlib.sha256()
            for frame in animation.frames:
                target.write(_LENGTH.pack(len(frame)))
                target.write(frame)
                checksum.update(frame)
            target.write(checksum.digest())
        temporary.replace(path)
    except OSError:
        pass  # Caching is optional, including on full or read-only disks.
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
