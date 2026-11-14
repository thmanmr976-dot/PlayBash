import json
import os

from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

CONFIG_FILE = DATA_DIR / "config.json"

DATA_DIR.mkdir(exist_ok=True)

DEFAULT_CONFIG = {
    "mode": "classic",
    "color": False,
    "fps": 30,
    "loop": True,
    "remember_last_video": True,
    "clear_on_exit": True,
    "hide_cursor": True
}


def load():

    if not os.path.exists(CONFIG_FILE):

        save(DEFAULT_CONFIG)

        return DEFAULT_CONFIG.copy()

    with open(CONFIG_FILE, "r") as f:

        return {**DEFAULT_CONFIG, **json.load(f)}


def save(config):

    with open(CONFIG_FILE, "w") as f:

        json.dump(config, f, indent=4)


def get(key):

    config = load()

    return config.get(key)


def set(key, value):

    config = load()

    config[key] = value

    save(config)

def reset():

    save(DEFAULT_CONFIG.copy())

def all():

    return load()
