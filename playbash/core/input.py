import sys
import termios
import tty
import select


class Keyboard:

    def __enter__(self):

        self.fd = sys.stdin.fileno()

        self.old = termios.tcgetattr(self.fd)

        tty.setcbreak(self.fd)

        return self

    def __exit__(self, exc_type, exc, tb):

        termios.tcsetattr(
            self.fd,
            termios.TCSADRAIN,
            self.old
        )

    def pressed(self):

        ready, _, _ = select.select(
            [sys.stdin],
            [],
            [],
            0
        )

        if ready:

            return sys.stdin.read(1)

        return None
