from pathlib import Path

from playbash.cli.parser import create_parser

from playbash.library import (
    add_video,
    list_videos,
    remove_video,
    clear_library,
    get_video,
    get_last_video,
    set_last_video,
)

from playbash.settings import (
    get,
    set,
    reset,
    all,
)


def main():

    parser = create_parser()
    args = parser.parse_args()

    if args.command == "add":

        try:
            added = add_video(args.video)
        except (ValueError, OSError) as error:
            parser.exit(1, f"playbash: {error}\n")
        if added:
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

        if not Path(target).expanduser().is_file():
            print("Video not found.")
            return

        target = str(Path(target).expanduser().resolve())
        if get("remember_last_video"):
            set_last_video(target)

        try:
            from playbash.core.player import play
            play(target, mode=args.mode, fps=args.fps)
        except (ValueError, OSError) as error:
            parser.exit(1, f"playbash: {error}\n")
        except KeyboardInterrupt:
            return

    elif args.command == "fastfetch":
        from playbash.core.fastfetch import show_fastfetch
        target = args.video
        if args.adjust and target is None:
            parser.error("fastfetch --adjust requires a video path or library index")
        try:
            if args.reset_logo:
                from playbash.core.logo_default import reset_default_logo
                reset_default_logo()
                return
            if target is not None and target.isdecimal():
                target = get_video(int(target) - 1)
                if target is None:
                    parser.exit(1, "playbash: Invalid library index. Use playbash list to see video numbers.\n")
            show_fastfetch(target, stop=args.stop, adjust=args.adjust)
        except (ValueError, OSError) as error:
            parser.exit(1, f"playbash: {error}\n")
        except KeyboardInterrupt:
            return

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

        if args.loop is not None:
            set("loop", args.loop)
            changed = True

        if args.color is not None:
            set("color", args.color)
            changed = True

        if changed:

            print("✓ Settings updated.")

        else:

            config = all()

            print("\nPlayBash Settings\n")

            for key, value in config.items():
                print(f"{key:<22} {value}")

    elif args.command == "version":

        print("PlayBash v0.9.1")

    else:

        parser.print_help()


if __name__ == "__main__":
    main()
