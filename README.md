# PlayBash

PlayBash is a terminal-based ASCII video player written in Python.

It converts video frames into ASCII art and renders them directly inside the terminal.

---

## Features

* Play videos as ASCII art
* Multiple rendering modes
* Video library
* Remember last played video
* Configurable FPS
* Configurable rendering mode
* Simple command-line interface

---

## Requirements

* Python 3.10+
* OpenCV
* Pillow

Install dependencies:

```bash
pip install opencv-python pillow
```

---

## Usage

Run a video:

```bash
python playbash.py run movie.mp4
```

Play the last video:

```bash
python playbash.py run
```

Play a video from the library:

```bash
python playbash.py run 1
```

Add a video:

```bash
python playbash.py add movie.mp4
```

Show the library:

```bash
python playbash.py list
```

Remove a video:

```bash
python playbash.py remove 1
```

Clear the library:

```bash
python playbash.py clear
```

Show or change settings:

```bash
python playbash.py config

python playbash.py config --fps 60

python playbash.py config --mode dense
```

Show version:

```bash
python playbash.py version
```

---

## Project Structure

```
playbash.py
cli/
core/
data/
library.py
settings.py
```

---

## Current Version

v0.6.0

---

## License

MIT License

