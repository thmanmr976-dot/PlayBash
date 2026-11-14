"""OpenCV decoding with a system FFmpeg fallback for unsupported codecs."""
import json
import subprocess

import cv2
import numpy as np


class FFmpegCapture:
    def __init__(self, path, *, keyboard=None):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "V:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, check=True, timeout=10,
        )
        stream = json.loads(probe.stdout)["streams"][0]
        self.width, self.height = stream["width"], stream["height"]
        if self.width < 1 or self.height < 1:
            raise ValueError("Invalid video dimensions")
        self.keyboard = keyboard
        if keyboard is not None:
            keyboard.wait()
        self.process = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-nostdin", "-noautorotate", "-i", str(path),
             "-map", "0:V:0", "-an", "-sn", "-dn",
             "-vf", f"scale={self.width}:{self.height}",
             "-pix_fmt", "bgr24", "-threads", "1", "-f", "rawvideo", "pipe:1"],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            bufsize=0 if keyboard is not None else -1,
        )

    def read(self):
        size = self.width * self.height * 3
        pipe = self.process.stdout
        if self.keyboard is None:
            data = pipe.read(size)
            if len(data) != size:
                return False, None
        else:
            data = bytearray(size)
            remaining = memoryview(data)
            while remaining:
                self.keyboard.wait(None, stream=pipe.fileno())
                count = pipe.readinto(remaining)
                if not count:
                    return False, None
                remaining = remaining[count:]
        return True, np.frombuffer(data, dtype=np.uint8).reshape(self.height, self.width, 3)

    def release(self):
        if self.process.poll() is None:
            self.process.terminate()
        self.process.stdout.close()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()


def open_video(path, prefer_ffmpeg=False, *, keyboard=None):
    """Return a capture and its first decoded frame, or a useful error."""
    if keyboard is not None:
        keyboard.wait()
    if not prefer_ffmpeg:
        capture = cv2.VideoCapture(str(path))
        keep = False
        try:
            if capture.isOpened():
                success, frame = capture.read()
                if success:
                    keep = True
                    return capture, frame
        except cv2.error:
            pass
        finally:
            if not keep:
                capture.release()

    capture = None
    keep = False
    try:
        if keyboard is not None:
            keyboard.wait()
        capture = FFmpegCapture(path, keyboard=keyboard)
        success, frame = capture.read()
        if success:
            keep = True
            return capture, frame
    except FileNotFoundError as error:
        raise ValueError("Could not decode video with OpenCV. Install FFmpeg and ffprobe for additional codecs.") from error
    except (subprocess.SubprocessError, ValueError, IndexError, KeyError, OSError) as error:
        raise ValueError(f"Could not decode video: {path}") from error
    finally:
        if capture is not None and not keep:
            capture.release()
    raise ValueError(f"Could not decode any video frames: {path}")
