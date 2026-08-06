#!/usr/bin/env python3

from pathlib import Path

from cli.parser import create_parser
from core.player import play

from library import (
    add_video,
    list_videos,
    remove_video,
    clear_library,
    get_video,
    get_last_video,
    set_last_video,
)

from settings import get (
    set,
    reset,
    all,
)


def main():

    parser = create_parser()
    args = parser.parse_args()

    if args.command == "add":

        if add_video(args.video):
            print("✓ Video added successfully.")
        else:
            print("Video already exists.")

    elif args.command == "list":

        videos = list_videos()

        if not videos:
            print("Library is empty.")
            return

        print("PlayBash Library\n")

        for i, video in enumerate(videos, start=1):
            print(f"{i}. {Path(video).name}")

    elif args.command == "remove":

        target = args.video

        if target.isdigit():

            if remove_video(int(target) - 1):
                print("✓ Video removed.")
            else:
                print("Invalid index.")

        else:
            print("Removing by path is not implemented yet.")

    elif args.command == "clear":

        clear_library()
        print("✓ Library cleared.")

    elif args.command == "run":

        target = args.video

        if target is None:

            target = get_last_video()

            if not target:
                print("No previous video found.")
                return

        elif target.isdigit():

            video = get_video(int(target) - 1)

            if video is None:
                print("Invalid library index.")
                return

            target = video

        if not Path(target).exists():
            print("Video not found.")
            return

        set_last_video(target)

        play(
            target,
            mode=args.mode,
            fps=args.fps
        )

    elif args.command == "config":

        if args.reset:

            reset()
            print("✓ Settings restored.")
            return

        changed = False

        if args.mode:

            set("mode", args.mode)
            changed = True

        if args.fps:

            set("fps", args.fps)
            changed = True

        if changed:

            print("✓ Settings updated.")

        else:

            config = all()

            print("\nPlayBash Settings\n")

            for key, value in config.items():
                print(f"{key:<22} {value}")

    elif args.command == "version":

        print("PlayBash v0.8.0-dev")

    else:

        parser.print_help()


if __name__ == "__main__":
    main()
