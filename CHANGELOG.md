# Changelog

All notable changes to PlayBash are documented here.

## [v0.9.1] — 2026-11-18

### Faster Fastfetch startup

* Persistent caching reuses the final rendered logo frames across terminal sessions, avoiding repeated video decoding and glyph rasterization.
* A local PTY benchmark measured **92.2% less warm-start wait**, from **2.797 s to 0.218 s** on average (**12.8× startup speedup**). This compares the same rendering setup before and after caching, with identical encoded video payloads.
* The benchmark used a 16.53-second local clip and a fixed 132×46 terminal grid; warm starts were 0.2202 s and 0.2160 s. The first uncached run took 2.831 s. These are process/PTY timings, not a measurement of terminal GPU rendering or a playback-FPS increase.
* Cache entries refresh when the video, terminal geometry, mode, colors, framing, or renderer changes. The disposable cache has a 256 MiB budget; corrupt or unwritable entries fall back to normal preparation.
* Playback timing now compensates for small scheduling delays instead of accumulating them.

### More symbols and clearer edges

Added directional strokes, curves, and partial block shapes to preserve contours across all six modes, including animated Fastfetch logos. Counts below exclude spaces:

| Mode | v0.9.0 | v0.9.1 | Increase |
| --- | ---: | ---: | ---: |
| `classic` | 13 | 21 | +61.5% |
| `dense` | 94 | 103 | +9.6% |
| `blocks` | 4 | 18 | +350.0% |
| `matrix` | 4 | 9 | +125.0% |
| `hex` | 16 | 20 | +25.0% |
| `binary` | 2 | 6 | +200.0% |

### Validation

* All 45 tests passed, including cache reuse in all six modes, color rendering, terminal restoration, and command input while the logo plays.

## [v0.9.0]

* Six ASCII rendering modes with optional video colors.
* Automatic replay, improved quit handling, and FFmpeg decoding fallback.
* Animated Fastfetch logos with framing controls and saved defaults.
* Project demo and GitHub Pages site.

## [v0.8.0]

### Added

* Global `playbash` command that can be used from any directory.
* New Python package structure.
* Linux installation script.
* Automatic virtual environment setup during installation.
* Automatic installation of Python dependencies.
* Global launcher for PlayBash.
* `pyproject.toml` package configuration.
* Improved project organization.
* Configurable rendering mode and FPS.
* Video library management.
* Last-played video support.

### Changed

* Migrated the project from standalone Python scripts to a proper Python package.
* Updated imports to use the `playbash` package structure.
* Improved installation workflow.
* Moved core functionality into the `playbash/` package.
* Moved application data into `playbash/data/`.
* Updated the CLI structure.
* Improved configuration and library handling.

### Fixed

* Fixed package import issues caused by the previous project structure.
* Fixed configuration and library paths when running PlayBash outside the project directory.
* Fixed installation issues related to Python's externally managed environment.
* Improved compatibility with standard Linux Python environments.

---

## [v0.7.0]

### Added

* Python package installation support.
* `playbash` command.
* Configuration commands.
* Video library commands.
* Project packaging with `pyproject.toml`.
* Installation script.

### Changed

* Major project restructuring.
* Moved core modules into organized directories.
* Improved CLI architecture.
* Improved configuration management.

---

## [v0.6.0]

### Added

* Video library system.
* `add` command.
* `list` command.
* `remove` command.
* `clear` command.
* `config` command.
* `version` command.
* Persistent settings.
* Last-played video tracking.

### Changed

* Improved command-line interface.
* Improved project organization.
* Separated playback, rendering, library, and settings functionality.

---

## [v0.5.0]

### Added

* Initial PlayBash CLI.
* ASCII video playback.
* Multiple rendering modes.
* FPS control.
* Terminal-sized rendering.
* Basic video playback functionality.

---

## Development

PlayBash is currently under active development.

Version numbers may change as features are tested and refined.
