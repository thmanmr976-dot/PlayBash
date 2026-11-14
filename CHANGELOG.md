# Changelog

All notable changes to PlayBash are documented here.

## [v0.9.0-dev]

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
