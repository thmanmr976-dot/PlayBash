import json
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
LIBRARY_FILE = DATA_DIR / "library.json"

DATA_DIR.mkdir(exist_ok=True)


def load_library():
    if not LIBRARY_FILE.exists():
        return {
            "last_video": "",
            "videos": []
        }

    with open(LIBRARY_FILE, "r") as f:
        return json.load(f)


def save_library(data):
    with open(LIBRARY_FILE, "w") as f:
        json.dump(data, f, indent=4)


def add_video(path):
    data = load_library()

    if path in data["videos"]:
        return False

    data["videos"].append(path)
    save_library(data)
    return True


def list_videos():
    return load_library()["videos"]


def remove_video(index):
    data = load_library()

    if index < 0 or index >= len(data["videos"]):
        return False

    data["videos"].pop(index)
    save_library(data)
    return True


def clear_library():
    save_library({
        "last_video": "",
        "videos": []
    })


def get_video(index):
    data = load_library()

    if index < 0 or index >= len(data["videos"]):
        return None

    return data["videos"][index]


def set_last_video(path):
    data = load_library()
    data["last_video"] = path
    save_library(data)


def get_last_video():
    return load_library()["last_video"]
