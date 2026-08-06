import argparse


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
        type=int,
        default=None,
        help="Playback FPS"
    )

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
        type=int
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
