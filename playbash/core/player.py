import shutil
import time

import cv2

from playbash.core.input import Keyboard
from playbash.settings import get
from playbash.core.ascii import frame_to_ascii
from playbash.core.renderer import (
    clear,
    hide_cursor,
    render,
    show_cursor,
)


def play(video_path, mode=None, fps=None):

    if mode is None:
        mode = get("mode")

    if fps is None:
        fps = get("fps")

    video = cv2.VideoCapture(video_path)

    if not video.isOpened():
        print(f"Could not open: {video_path}")
        return

    cols, rows = shutil.get_terminal_size()

    width = cols
    height = max(rows - 1, 1)

    clear()
    hide_cursor()

    frame_time = 1 / fps

    try:

       with Keyboard() as keyboard:

          while True:

            start = time.perf_counter()

            success, frame = video.read()

            if not success:
                break

            frame = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            ascii_frame = frame_to_ascii(
                frame,
                width,
                height,
                mode
            )

            render(ascii_frame)

            key = keyboard.pressed()

            if key == "q":
                break

            elapsed = time.perf_counter() - start

            sleep_time = frame_time - elapsed

            if sleep_time > 0:
                time.sleep(sleep_time)

    finally:

        video.release()

        show_cursor()

        clear()
