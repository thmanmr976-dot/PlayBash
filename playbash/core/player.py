import math
import sys
import shutil
import time

import cv2

from playbash.core.input import Keyboard, PlaybackStopped
from playbash.core.video import FFmpegCapture, open_video
from playbash.settings import all as load_settings
from playbash.core.ascii import cell_colors, gray_to_ascii
from playbash.core.renderer import (
    ColorRenderer,
    ColoredFrame,
    clear,
    hide_cursor,
    render,
    reset_foreground,
    show_cursor,
)


CHAR_ASPECT = 0.5


def calc_dimensions():

    cols, rows = shutil.get_terminal_size()

    width = max(cols, 1)
    height = max(rows - 1, 1)

    return width, height


def crop_to_aspect(frame, target_width, target_height):

    frame_h, frame_w = frame.shape[:2]

    term_aspect = (target_width / target_height) * CHAR_ASPECT
    video_aspect = frame_w / frame_h

    if video_aspect > term_aspect:

        new_w = max(1, int(frame_h * term_aspect))
        x0 = (frame_w - new_w) // 2
        frame = frame[:, x0:x0 + new_w]

    else:

        new_h = max(1, int(frame_w / term_aspect))
        y0 = (frame_h - new_h) // 2
        frame = frame[y0:y0 + new_h, :]

    return frame


def play(video_path, mode=None, fps=None):
    settings = load_settings()
    mode = mode if mode is not None else settings.get("mode", "classic")
    fps = fps if fps is not None else settings.get("fps", 30)
    color = settings.get("color", False)
    if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
        raise ValueError("FPS must be a finite number greater than zero")
    from playbash.core.charset import CHARSETS
    if mode not in CHARSETS:
        raise ValueError(f"Unknown rendering mode: {mode}")
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Playback requires an interactive terminal")

    video = None
    cursor_hidden = False
    started = False
    color_renderer = ColorRenderer(sys.stdout) if color else None
    try:
        with Keyboard() as keyboard:
            video, frame = open_video(video_path, keyboard=keyboard)
            loop = settings.get("loop", True)
            keyboard.wait()
            clear()
            started = True
            if settings.get("hide_cursor", True):
                cursor_hidden = True
                hide_cursor()
            frame_time = 1 / fps
            while True:
                start = time.perf_counter()
                if frame is None:
                    success, frame = video.read()
                    if not success:
                        if not loop:
                            break
                        prefer_ffmpeg = isinstance(video, FFmpegCapture)
                        video.release()
                        video = None
                        video, frame = open_video(video_path, prefer_ffmpeg, keyboard=keyboard)
                    keyboard.wait()
                width, height = calc_dimensions()
                frame = crop_to_aspect(frame, width, height)
                if frame.shape[2:] in ((), (1,)):
                    gray = frame.reshape(frame.shape[:2])
                else:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                symbols = gray_to_ascii(gray, width, height, mode)
                if color_renderer is not None:
                    colors = cell_colors(frame, width, height, bgr=True)
                    color_renderer.render(ColoredFrame(tuple(symbols), colors.tobytes()))
                else:
                    render(symbols)
                frame = None
                delay = frame_time - (time.perf_counter() - start)
                keyboard.wait(max(0, delay))
    except PlaybackStopped:
        pass
    finally:
        if video is not None:
            video.release()
        if color and started:
            reset_foreground()
        if cursor_hidden:
            show_cursor()
        if started and settings.get("clear_on_exit", True):
            clear()
