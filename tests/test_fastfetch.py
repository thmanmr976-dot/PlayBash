"""Verify the animated logo layout and the prompt that follows it."""
import errno
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from unittest.mock import Mock, patch
import zlib

import numpy as np

from playbash.core.charset import CHARSETS
from playbash.core.fastfetch import Grid, Layout, Logo, RasterLogo, measure_logo, prepare_layout, show_fastfetch
from playbash.core.logo_default import load_default_logo, native_fastfetch, reset_default_logo, save_default_logo
from playbash.core.logo_video import AdjustableAnimation, GlyphRaster, LogoAnimation, prepare_video, raster_size, symbol_scale
from playbash.core.logo_shell import CONTROL_ENV, LogoViewport
from playbash.core.renderer import ColoredFrame


class FastfetchLayoutTests(unittest.TestCase):
    def test_missing_fastfetch_is_reported_before_using_terminal(self):
        with patch("playbash.core.fastfetch.shutil.which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Fastfetch is not installed"):
                show_fastfetch("clip.webm")

    def test_default_logo_keeps_native_fastfetch_and_forwards_arguments(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            native = home / "system" / "fastfetch"
            native.parent.mkdir()
            native.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            native.chmod(0o755)
            bashrc = home / ".bashrc"
            original = "fastfetch\n"
            bashrc.write_text(original)
            local_bin = home / ".local" / "bin"
            with patch.dict(os.environ, HOME=str(home), XDG_CONFIG_HOME=folder, SHELL="/bin/bash",
                            PATH=os.pathsep.join(map(str, (local_bin, native.parent, "/usr/bin")))):
                video = home / "a video.webm"
                save_default_logo(video, (1.15, 0.15, 0), str(native))
                save_default_logo(video, (1.15, 0.15, 0), str(native))
                self.assertEqual(load_default_logo(), (str(video), (1.15, 0.15, 0)))
                self.assertEqual(native_fastfetch(), str(native))
                self.assertTrue(bashrc.read_text().endswith(original))
                self.assertEqual(bashrc.read_text().count("# >>> PlayBash Fastfetch >>>"), 1)
                output = subprocess.check_output([local_bin / "fastfetch", "--version", "two words"], text=True)
                self.assertEqual(output.splitlines(), ["--version", "two words"])
                reset_default_logo()
                self.assertIsNone(load_default_logo())
                self.assertEqual(bashrc.read_text(), original)

    def test_save_refuses_to_replace_an_unrelated_launcher(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, HOME=folder, XDG_CONFIG_HOME=folder):
            path = Path(folder) / ".local/bin/fastfetch"
            path.parent.mkdir(parents=True)
            path.write_text("existing launcher")
            with self.assertRaisesRegex(ValueError, "different Fastfetch launcher"):
                save_default_logo("clip.webm", None, "/usr/bin/fastfetch")
            self.assertEqual(path.read_text(), "existing launcher")
            self.assertIsNone(load_default_logo())

    def test_logo_size_uses_visible_cells_or_image_extent(self):
        grid = Grid(80, 30, 800, 600)
        self.assertEqual(measure_logo(b"\x1b[32m###\x1b[0m\n###\n\n", grid), Logo(3, 2))
        image = b"\x1b_Ga=T,f=24,s=101,v=81,m=1;AAAA\x1b\\"
        self.assertEqual(measure_logo(image, grid), Logo(11, 5))

    def test_layout_keeps_padding_and_module_text(self):
        grid = Grid(80, 30, 800, 600)
        output = b"Title\n  ###   \x1b[32mCPU\x1b[0m\n  ###   RAM\n\n"
        layout = prepare_layout(output, "#", Logo(3, 2), grid)
        self.assertEqual(layout.logo, Logo(3, 2))
        self.assertEqual((layout.column, layout.rows_above_cursor), (2, 3))
        self.assertEqual(layout.output, output.replace(b"#", b" "))

    def test_right_logo_anchor_respects_fastfetch_cursor_moves(self):
        grid = Grid(80, 30, 800, 600)
        output = b"\x1b[9999999C\x1b[5D###\x1b[GCPU\n"
        layout = prepare_layout(output, "#", Logo(3, 1), grid)
        self.assertEqual(layout.column, 74)
        self.assertEqual(layout.rows_above_cursor, 1)

    def test_too_small_terminal_is_not_resized(self):
        with self.assertRaisesRegex(ValueError, "wider"):
            prepare_layout(b"### long text\n", "#", Logo(3, 1), Grid(6, 20, 60, 400))

    def test_only_the_logo_glyphs_are_opaque(self):
        raster = GlyphRaster("dense", (64, 32))
        self.assertEqual(set(raster.pixels(("  ",))[3::4]), {0})
        alpha = raster.pixels(("@ ",))[3::4]
        self.assertGreater(max(alpha), 0)
        self.assertTrue(all(value == 0 for row in range(32)
                            for value in alpha[row * 64 + 48:(row + 1) * 64]))

    def test_adjusted_logo_reuses_raster_until_the_view_moves(self):
        source = bytes(range(64)) * 4
        compressed = zlib.compress(source)
        animation = AdjustableAnimation((compressed, compressed, source), 83, 8, 4,
                                        (1.0, 1.0), "dense", (16, 16))
        encode = Mock(side_effect=lambda frame: "\n".join(frame).encode())
        self.assertEqual(animation.frame(0), animation.frame(2))
        first = animation.frame(0, encode=encode)
        self.assertEqual(first, animation.frame(1, encode=encode))
        self.assertEqual(encode.call_count, 1)
        animation.adjust("right")
        self.assertNotEqual(first, animation.frame(0, encode=encode))
        self.assertEqual(encode.call_count, 2)

    def test_adjusted_color_logo_reuses_frames_beyond_the_memory_cache(self):
        source = bytes(range(64)) * 12
        with tempfile.TemporaryFile() as spool, patch("playbash.core.logo_video.MAX_RENDER_CACHE_BYTES", 1):
            spool.write(source)
            animation = AdjustableAnimation(((0, len(source)),), 83, 8, 4,
                                            (1.0, 1.0), "dense", (16, 16, 3), spool)
            encode = Mock(side_effect=lambda frame: frame.colors)
            try:
                frame = animation.frame(0, encode=encode)
                self.assertEqual(animation.frame(0, encode=encode), frame)
                self.assertEqual(encode.call_count, 1)
                animation.adjust("right")
                self.assertNotEqual(animation.frame(0, encode=encode), frame)
                self.assertEqual(encode.call_count, 2)
            finally:
                animation.release_frames()

    def test_tint_keeps_the_same_alpha_mask_for_each_style(self):
        for mode, palette in CHARSETS.items():
            with self.subTest(mode=mode):
                lines = (f"{palette[0]}  {palette[0]}",)
                raster = GlyphRaster(mode, (80, 24))
                frame = ColoredFrame(lines, b"\xff\0\0" + bytes(6) + b"\0\0\xff")
                pixels = np.frombuffer(raster.pixels(frame), dtype=np.uint8).reshape(24, 80, 4)
                alpha = pixels[:, :, 3]
                self.assertEqual(alpha.tobytes(), raster.pixels(lines)[3::4])
                self.assertTrue(np.any(np.all(pixels[:, :20] == (255, 0, 0, 255), axis=2)))
                self.assertTrue(np.any(np.all(pixels[:, 60:] == (0, 0, 255, 255), axis=2)))
                self.assertTrue(np.all(alpha[:, 35:45] == 0))


class ViewportTests(unittest.TestCase):
    def viewport(self):
        return LogoViewport(Layout(b"", 2, 3, Logo(3, 2)), Grid(12, 5, 96, 80), 3, 0)

    def test_logo_follows_scroll_and_only_paints_visible_rows(self):
        screen = self.viewport()
        screen.feed(b"hello\r\nworld\r\n")
        output = screen.paint(("abc", "def"))
        self.assertNotIn(b"abc", output)
        self.assertIn(b"\x1b[1;3Hdef", output)
        self.assertIn(b"\x1b[5;1H", output)
        screen.feed(b"\r\n")
        self.assertEqual(screen.paint(("abc", "def")), b"")

    def test_konsole_replaces_one_image_and_clips_scrolled_rows(self):
        screen = self.viewport()
        frame = ("abcdef", "abcdef", "abcdef", "abcdef")
        logo = RasterLogo(screen.layout, LogoAnimation((frame,), 83), screen.grid, "dense")
        initial = logo.paint(screen, 0)
        self.assertIn(b",p=1,", initial)
        self.assertIn(b",c=3,r=2,C=1", initial)
        screen.feed(b"hello\r\nworld\r\n")
        clipped = logo.paint(screen, 0)
        self.assertTrue(clipped.startswith(b"\x1b[1;3H"))
        self.assertIn(b",p=1,", clipped)
        self.assertIn(b",c=3,r=1,C=1", clipped)
        self.assertIn(b",y=16,h=16", clipped)
        self.assertTrue(clipped.endswith(b"\x1b[5;1H"))

    def test_partial_sequences_pause_and_alternate_screen_is_respected(self):
        screen = self.viewport()
        screen.feed(b"\x1b[?104")
        self.assertEqual(screen.paint(("abc", "def")), b"")
        screen.feed(b"9h\x1b[H\x1b[2Jeditor")
        self.assertEqual(screen.paint(("abc", "def")), b"")
        screen.feed(b"\x1b[?1049l")
        self.assertIn(b"\x1b[1;3Habc", screen.paint(("abc", "def")))
        screen.feed(b"\x1b[2J")
        self.assertEqual(screen.paint(("abc", "def")), b"")

    def test_shell_output_over_logo_disables_animation(self):
        screen = self.viewport()
        screen.feed(b"\x1b[1;3Htyped")
        self.assertEqual(screen.paint(("abc", "def")), b"")


@unittest.skipUnless(all(shutil.which(p) for p in ("fastfetch", "ffmpeg", "ffprobe", "bash")),
                     "Fastfetch, FFmpeg and Bash are needed for the integration test")
class FastfetchShellTests(unittest.TestCase):
    def make_fixture(self, root, source="testsrc2=size=64x48:rate=12:duration=0.5"):
        config = root / "fastfetch"
        config.mkdir()
        logo = root / "test-logo.txt"
        logo.write_text("AAAAAA\nAAAAAA\nAAAAAA\n")
        (config / "config.jsonc").write_text(json.dumps({
            "logo": {"type": "file-raw", "source": str(logo),
                     "padding": {"left": 2, "right": 3}},
            "modules": [{"type": "custom", "format": name}
                        for name in ("TEST_CPU", "TEST_RAM", "TEST_OS", "TEST_SHELL")],
        }))
        video = root / "sample video.mp4"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", source, "-c:v", "mpeg4",
             "-threads", "1", str(video)], check=True, timeout=10,
        )
        return video

    def test_denser_video_uses_same_pixels_with_four_times_as_many_cells(self):
        with tempfile.TemporaryDirectory(prefix="playbash-logo-density-") as folder:
            video = self.make_fixture(Path(folder))
            logo = Logo(6, 3)
            grid = Grid(100, 32, 900, 640)
            before = prepare_video(video, logo, grid, "dense")
            after = prepare_video(video, logo, grid, "dense", symbol_scale(logo, grid))
            old, new = before.frames[0], after.frames[0]
            self.assertEqual((len(old), len(old[0])), (3, 6))
            self.assertEqual((len(new), len(new[0])), (6, 12))
            raster = GlyphRaster("dense", raster_size(logo, grid))
            self.assertEqual(len(raster.pixels(old)), len(raster.pixels(new)))
            self.assertNotEqual(raster.pixels(old), raster.pixels(new))

    def test_center_zoom_removes_edges_before_converting_video_to_symbols(self):
        with tempfile.TemporaryDirectory(prefix="playbash-logo-zoom-") as folder:
            logo = Logo(12, 6)
            grid = Grid(80, 24, 640, 384)  # The logo is square in pixels.
            for name, source, box in (("wide", "120x60", "30:0:60:60"),
                                      ("square", "100x100", "4:4:92:92")):
                with self.subTest(source=source):
                    video = Path(folder) / f"{name}.mkv"
                    subprocess.run(
                        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                         f"color=white:s={source}:r=12:d=0.25,drawbox={box}:black:t=fill",
                         "-c:v", "ffv1", "-threads", "1", str(video)], check=True, timeout=10,
                    )
                    frame = prepare_video(video, logo, grid, "dense").frames[0]
                    # The center is black; the white border should not be
                    # represented by spaces anywhere inside the logo.
                    symbols = set("".join(frame))
                    self.assertEqual(len(symbols), 1)
                    self.assertNotIn(" ", symbols)

    def test_color_source_reaches_each_style_in_fixed_and_adjustable_logos(self):
        with tempfile.TemporaryDirectory(prefix="playbash-logo-color-") as directory:
            video = self.make_fixture(Path(directory), "color=red:s=128x96:r=12:d=0.5,"
                                      "drawbox=64:0:64:96:blue:t=fill")
            logo = Logo(12, 6)
            grid = Grid(100, 32, 900, 640)
            # Force the adjustable source spool onto disk with this small clip.
            with patch("playbash.core.logo_video.COLOR_SPOOL_BYTES", 1):
                for mode, palette in CHARSETS.items():
                    for adjust in (False, True):
                        with self.subTest(mode=mode, adjust=adjust):
                            animation = prepare_video(video, logo, grid, mode, adjust=adjust, color=True)
                            try:
                                if adjust:
                                    spool = animation.source_file
                                    animation.adjust("right")
                                frame = animation.frame(0)
                                self.assertIsInstance(frame, ColoredFrame)
                                self.assertEqual(len(frame.lines), logo.rows)
                                self.assertTrue(all(len(line) == logo.columns for line in frame.lines))
                                self.assertLessEqual(set("".join(frame.lines)), set(palette + " "))
                                colors = np.frombuffer(frame.colors, dtype=np.uint8).reshape(-1, 3)
                                self.assertTrue(np.any((colors[:, 0] > 200) & (colors[:, 2] < 50)))
                                self.assertTrue(np.any((colors[:, 0] < 50) & (colors[:, 2] > 200)))
                            finally:
                                animation.release_frames()
                            if adjust:
                                self.assertTrue(spool.closed)

    def test_animation_returns_to_same_shell_and_keeps_geometry(self):
        with tempfile.TemporaryDirectory(prefix="playbash-logo-test-") as folder:
            root = Path(folder)
            video = self.make_fixture(root)
            self.check_shell(root, video, save=False)
            self.check_shell(root, video)

    def test_saved_framing_reopens_with_the_same_symbols(self):
        with tempfile.TemporaryDirectory() as folder:
            video = self.make_fixture(Path(folder))
            logo, grid = Logo(12, 6), Grid(100, 32, 900, 640)
            preview = prepare_video(video, logo, grid, "dense", adjust=True, color=True)
            try:
                preview.adjust("right")
                preview.adjust("+")
                saved = prepare_video(video, logo, grid, "dense", color=True, framing=preview.framing)
                self.assertEqual(saved.gap_ms, preview.gap_ms)
                self.assertEqual(saved.frame(0), preview.frame(0))
            finally:
                preview.release_frames()

    def test_non_kitty_keeps_typing_and_animation_in_same_pty(self):
        for konsole, color in ((False, False), (False, True), (True, False)):
            with self.subTest(konsole=konsole, color=color):
                self.check_interactive(konsole, color=color)

    def test_adjustment_keys_change_the_frame_and_enter_releases_the_shell(self):
        for color in (False, True):
            with self.subTest(color=color):
                self.check_interactive(konsole=False, adjust=True, color=color)

    def test_q_closes_the_adjustable_preview_without_saving(self):
        self.check_interactive(konsole=False, adjust=True, quit_preview=True)

    def check_interactive(self, konsole, adjust=False, color=False, quit_preview=False):
        with tempfile.TemporaryDirectory(prefix="playbash-logo-shell-") as folder:
            root = Path(folder)
            if adjust:
                # Static source so changes can only come from a control key.
                video = self.make_fixture(root, "color=black:s=128x96:r=12:d=0.5,"
                                          "drawbox=48:20:25:40:white:t=fill,"
                                          "drawbox=75:62:24:24:gray:t=fill")
            else:
                video = self.make_fixture(root)
            (root / ".bashrc").write_text("PS1='LOGO_PROMPT> '\nfastfetch\n")
            master, slave = pty.openpty()
            geometry = struct.pack("HHHH", 32, 100, 900, 640)
            fcntl.ioctl(slave, termios.TIOCSWINSZ, geometry)
            tty_settings = termios.tcgetattr(slave)
            env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root),
                       SHELL=shutil.which("bash"), TERM="xterm-256color",
                       PYTHONDONTWRITEBYTECODE="1")
            for key in ("KITTY_WINDOW_ID", "KONSOLE_VERSION", "KONSOLE_DBUS_SESSION", "TMUX", "STY", CONTROL_ENV):
                env.pop(key, None)
            if konsole:
                env["KONSOLE_VERSION"] = "260800"
            command = [sys.executable, "-c", (
                "from playbash.core import fastfetch as f; from playbash.__main__ import main; "
                f"f.load_settings=lambda:{{'mode':'binary','color':{color}}}; main()"
            ), "fastfetch", str(video)]
            if adjust:
                command.append("--adjust")
            process = subprocess.Popen(command, stdin=slave, stdout=slave, stderr=slave, env=env,
                                       start_new_session=True)
            data = bytearray()

            def read_until(predicate, limit=8):
                deadline = time.monotonic() + limit
                while not predicate() and time.monotonic() < deadline:
                    if select.select([master], [], [], 0.05)[0]:
                        data.extend(os.read(master, 65536))
                    elif process.poll() is not None:
                        break
                self.assertTrue(predicate(), data[-1000:].decode(errors="replace"))

            def shell_output():
                # Shell output and a logo refresh can arrive between the
                # two writes that print the marker and terminal size.
                raster = re.sub(rb"\x1b_G[^\x1b]*\x1b\\", b"", data)
                return re.sub(rb"\x1b\[m(?:\x1b\[\d+;3H(?:\x1b\[\d+(?:;\d+)*m|[01 ])+)+\x1b\[\d+;\d+H\x1b\[m",
                              b"", raster)

            def drawings():
                if konsole:
                    return data.count(b"\x1b_Ga=T,i=")
                return len(re.findall(rb"\x1b\[\d+;3H[01 ]{6}", glyph_output()))

            def glyph_output():
                return re.sub(rb"\x1b\[(?:38;2;\d+;\d+;\d+|39)m", b"", data) if color else data

            def text_frames():
                row = rb"\x1b\[\d+;3H([01 ]{6})"
                return re.findall(row * 3, glyph_output())

            try:
                read_until(lambda: b"\x1b[6n" in data)
                before_query = data.partition(b"\x1b[6n")[0]
                row = before_query.count(b"\n") + 1
                os.write(master, f"\x1b[{row};1R".encode())
                read_until(lambda: b"LOGO_PROMPT> " in data and drawings() >= 6)
                if quit_preview:
                    os.write(master, b"q")
                    self.assertEqual(process.wait(timeout=2), 0)
                    self.assertFalse((root / "playbash" / "fastfetch.json").exists())
                    self.assertEqual(termios.tcgetattr(slave), tty_settings)
                    return
                command = b"printf 'NEXT_COMMAND_RAN\\n'; stty size\n"
                if adjust:
                    previous = text_frames()[-1]
                    count = len(text_frames())
                    os.write(master, b"\x1b[")
                    read_until(lambda: len(text_frames()) > count)
                    self.assertEqual(text_frames()[-1], previous)
                    adjustments = (b"C\x1b[C", b"\x1bOB\x1bOB", b"+++", b"---",
                                   b"\x1b[D\x1b[D", b"\x1b[A\x1b[A")
                    for keys in adjustments:
                        with self.subTest(keys=keys):
                            count = len(text_frames())
                            os.write(master, keys)
                            read_until(lambda: any(frame != previous for frame in text_frames()[count:]))
                            previous = text_frames()[-1]
                # The shell command follows the Enter handoff in the same read.
                os.write(master, b"\r" + command)
                read_until(lambda: b"NEXT_COMMAND_RAN\r\n32 100" in shell_output())
                choice = json.loads((root / "playbash" / "fastfetch.json").read_text())
                self.assertEqual(choice["video"], str(video))
                self.assertEqual(choice["framing"] is not None, adjust)
                initial_draws = drawings()
                read_until(lambda: drawings() > initial_draws)
                if adjust:
                    self.assertEqual(text_frames()[-1], previous)
                stop = shlex.join([sys.executable, "-m", "playbash", "fastfetch", "--stop"])
                os.write(master, (stop + " && printf 'STOPPED_LOGO\\n'\n").encode())
                read_until(lambda: b"STOPPED_LOGO\r\n" in data)
                os.write(master, b"exit\n")
                self.assertEqual(process.wait(timeout=4), 0)
                self.assertIn(b"TEST_CPU", data)
                if konsole:
                    self.assertIn(b",c=6,r=3,C=1", data)
                    self.assertIn(b"a=d,d=I", data)
                else:
                    self.assertNotIn(b"\x1b_G", data)
                if color:
                    self.assertIn(b"\x1b[38;2;", data)
                    self.assertIn(b"\x1b[39m", data)
                self.assertEqual(fcntl.ioctl(slave, termios.TIOCGWINSZ, bytes(8)), geometry)
                self.assertEqual(termios.tcgetattr(slave), tty_settings)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=4)
                os.close(master)
                os.close(slave)

    def check_shell(self, root, video, save=True):
        master, slave = pty.openpty()
        geometry = struct.pack("HHHH", 32, 100, 900, 640)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, geometry)
        tty_settings = termios.tcgetattr(slave)
        command = shlex.join([sys.executable, "-m", "playbash", "fastfetch", str(video)])
        # Continue using the same shell after the logo command. No workers need
        # to write to the PTY while the shell reads commands from the keyboard.
        script = command + " && printf 'NEXT_COMMAND_RAN\\n' && stty size"
        env = dict(os.environ, HOME=str(root), XDG_CONFIG_HOME=str(root), SHELL=shutil.which("bash"), TERM="xterm-kitty",
                   PYTHONDONTWRITEBYTECODE="1")
        env.pop("TMUX", None)
        env.pop("STY", None)
        process = subprocess.Popen(
            ["bash", "--noprofile", "--norc", "-c", script],
            stdin=slave, stdout=slave, stderr=slave, env=env, start_new_session=True,
        )
        data = bytearray()
        sent_enter = False
        deadline = time.monotonic() + 12
        try:
            while process.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    data.extend(os.read(master, 65536))
                if not sent_enter and b",s=3,v=1,q=2" in data:
                    if not termios.tcgetattr(slave)[3] & termios.ICANON:
                        os.write(master, b"\r" if save else b"q")
                        sent_enter = True
            self.assertIsNotNone(process.poll(), "Logo command did not return")
            while select.select([master], [], [], 0)[0]:
                try:
                    data.extend(os.read(master, 65536))
                except OSError as error:
                    if error.errno != errno.EIO:
                        raise
                    break
            self.assertEqual(process.returncode, 0, data[-1000:].decode(errors="replace"))
            self.assertIn(b"TEST_CPU", data)
            self.assertNotIn(b"AAAAAA", data)
            self.assertIn(b",c=6,r=3,C=1", data)
            self.assertGreater(data.count(b"\x1b_Ga=f,i="), 1)
            self.assertIn(b",s=3,v=1,q=2", data)
            self.assertIn(b"NEXT_COMMAND_RAN\r\n32 100", data)
            saved = root / "playbash" / "fastfetch.json"
            if save:
                self.assertEqual(json.loads(saved.read_text()), {"video": str(video), "framing": None})
            else:
                self.assertFalse(saved.exists())
                self.assertGreater(data.rfind(b"a=d,d=I"), data.rfind(b",s=3,v=1,q=2"))
            self.assertNotIn(b"\x1b[8;", data)
            self.assertEqual(fcntl.ioctl(slave, termios.TIOCGWINSZ, bytes(8)), geometry)
            self.assertEqual(termios.tcgetattr(slave), tty_settings)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait()
            os.close(master)
            os.close(slave)


if __name__ == "__main__":
    unittest.main()
