import sys


def clear():
    sys.stdout.write("\033[2J")
    sys.stdout.flush()


def home():
    sys.stdout.write("\033[H")


def hide_cursor():
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()


def show_cursor():
    sys.stdout.write("\033[?25h")
    sys.stdout.flush()


def render(frame):

    home()

    sys.stdout.write("\n".join(frame))

    sys.stdout.flush()
