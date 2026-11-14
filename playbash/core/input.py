import os
import select
import sys
import termios
import time
import tty


class PlaybackStopped(Exception):
    """The user pressed the playback quit key."""


class Keyboard:
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        try:
            tty.setcbreak(self.fd, termios.TCSANOW)
            return self
        except BaseException:
            termios.tcsetattr(self.fd, termios.TCSANOW, self.old)
            raise

    def __exit__(self, exc_type, exc, tb):
        termios.tcsetattr(self.fd, termios.TCSANOW, self.old)

    def wait(self, timeout=0, *, stream=None):
        """Wait for a frame deadline or readable decoder pipe, checking for quit."""
        deadline = None if timeout is None else time.monotonic() + timeout
        readers = [self.fd] if stream is None else [self.fd, stream]
        while True:
            remaining = None if deadline is None else max(0, deadline - time.monotonic())
            ready, _, _ = select.select(readers, [], [], remaining)
            if self.fd in ready:
                # Reading through sys.stdin can hide queued keys in its buffer,
                # where select() on the terminal descriptor cannot see them.
                keys = os.read(self.fd, 4096)
                if not keys or b"q" in keys or b"Q" in keys:
                    raise PlaybackStopped
            if not ready or (stream is not None and stream in ready):
                return
