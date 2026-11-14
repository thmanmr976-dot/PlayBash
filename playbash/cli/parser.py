import argparse


def positive_fps(value):
    value = int(value)
    if value <= 0:
        raise argparse.ArgumentTypeError("FPS must be greater than zero")
    return value


def create_parser():

    parser = argparse.ArgumentParser(
        prog="playbash",
        description="Play videos as ASCII art in your terminal."
    )

    subparsers = parser.add_subparsers(
        dest="command"
    )

    # ---------------- RUN ----------------

    run = subparsers.add_parser(
        "run",
        help="Run a video"
    )

    run.add_argument(
        "video",
        nargs="?",
        help="Video path or library index"
    )

    run.add_argument(
        "-m",
        "--mode",
        default=None,
        choices=[
            "classic",
            "dense",
            "blocks",
            "matrix",
            "hex",
            "binary"
        ],
        help="Rendering mode"
    )

    run.add_argument(
        "-f",
        "--fps",
        type=positive_fps,
        default=None,
        help="Playback FPS"
    )

    fastfetch = subparsers.add_parser(
        "fastfetch", help="Loop a video in the Fastfetch logo area"
    )
    logo_action = fastfetch.add_mutually_exclusive_group()
    logo_action.add_argument("video", nargs="?", help="Video path or index from playbash list")
    logo_action.add_argument("--stop", action="store_true", help="Stop the animated logo in this terminal")
    logo_action.add_argument("--reset-logo", action="store_true", help="Restore the original Fastfetch logo")
    fastfetch.add_argument("--adjust", action="store_true",
                           help="Move and zoom the video before saving it with Enter")

    # ---------------- ADD ----------------

    add = subparsers.add_parser(
        "add",
        help="Add video to library"
    )

    add.add_argument(
        "video"
    )

    # ---------------- LIST ----------------

    subparsers.add_parser(
        "list",
        help="Show library"
    )

    # ---------------- REMOVE ----------------

    remove = subparsers.add_parser(
        "remove",
        help="Remove video"
    )

    remove.add_argument(
        "video"
    )

    # ---------------- CLEAR ----------------

    subparsers.add_parser(
        "clear",
        help="Clear library"
    )

    # ---------------- CONFIG ----------------

    config = subparsers.add_parser(
        "config",
        help="View or change PlayBash settings"
    )

    config.add_argument(
        "--mode",
        choices=[
            "classic",
            "dense",
            "blocks",
            "matrix",
            "hex",
            "binary"
        ]
    )

    config.add_argument(
        "--fps",
        type=positive_fps
    )

    config.add_argument(
        "--loop", action=argparse.BooleanOptionalAction,
        help="Enable or disable automatic replay (enabled by default)"
    )

    config.add_argument(
        "--color", action=argparse.BooleanOptionalAction,
        help="Show video colors in every rendering mode, including Fastfetch"
    )

    config.add_argument(
        "--reset",
        action="store_true"
    )

    # ---------------- VERSION ----------------

    subparsers.add_parser(
        "version",
        help="Show version"
    )

    return parser
