"""Check visible ASCII shapes and compatibility of the existing modes."""

from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from playbash import settings
from playbash.__main__ import main
from playbash.cli.parser import create_parser
from playbash.core.ascii import cell_colors, frame_to_ascii
from playbash.core.charset import CHARSETS
from playbash.core.renderer import ColoredFrame, ColorRenderer, ansi_lines


STYLIZED_PALETTES = {
    "blocks": "█▓▒░ ",
    "matrix": "@#01",
    "hex": "0123456789ABCDEF",
    "binary": "01",
}


class ASCIIRenderingTests(unittest.TestCase):
    def test_color_adds_foreground_only_in_each_style(self):
        rgb = np.zeros((36, 48, 3), dtype=np.uint8)
        rgb[:, :24, 0] = 255
        rgb[:, 24:, 2] = 255
        colors = cell_colors(rgb[:, :, ::-1], 8, 4, bgr=True).tobytes()
        for mode in CHARSETS:
            with self.subTest(mode=mode):
                glyphs = tuple(frame_to_ascii(rgb, 8, 4, mode))
                lines = ansi_lines(ColoredFrame(glyphs, colors))
                self.assertEqual(tuple(re.sub(r"\x1b\[[0-9;]*m", "", row) for row in lines), glyphs)
                self.assertIn("\x1b[38;2;255;0;0m", lines[0])
                self.assertIn("\x1b[38;2;0;0;255m", lines[0])
                self.assertTrue(lines[0].endswith("\x1b[39m"))

    def test_color_setting_is_optional_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"mode": "dense", "fps": 24}')
            with patch.object(settings, "CONFIG_FILE", path), redirect_stdout(io.StringIO()):
                self.assertFalse(settings.get("color"))
                for flag, enabled in (("--color", True), ("--no-color", False)):
                    with patch("sys.argv", ["playbash", "config", flag]):
                        main()
                    self.assertIs(settings.get("color"), enabled)
                    self.assertEqual(settings.get("mode"), "dense")
                    self.assertEqual(settings.get("fps"), 24)

    def test_color_renderer_draws_only_changed_cells_and_resets_foreground(self):
        red, blue = b"\xff\0\0", b"\0\0\xff"
        output = io.StringIO()
        renderer = ColorRenderer(output)
        renderer.render(ColoredFrame(("X█X", "ZZZ"), red * 6))
        first = output.getvalue()
        frame = ColoredFrame(("X█ ", "ZZZ"), red + blue + red * 4)
        renderer.render(frame)
        self.assertEqual(output.getvalue()[len(first):], "\x1b[1;2H\x1b[38;2;0;0;255m█ \x1b[39m\x1b[3;1H")
        drawn = output.tell()
        renderer.render(frame)
        self.assertEqual(output.tell(), drawn)
        renderer.render(ColoredFrame(("X",), red))
        self.assertEqual(output.getvalue()[drawn:], "\x1b[2J\x1b[H\x1b[38;2;255;0;0mX\x1b[39m\x1b[2;1H")

    def test_classic_and_dense_output_printable_ascii_at_terminal_size(self):
        frame = np.random.default_rng(42).integers(0, 256, (31, 47, 3), dtype=np.uint8)
        for mode in ("classic", "dense"):
            for width, height in ((1, 1), (2, 1), (1, 3), (11, 7)):
                with self.subTest(mode=mode, width=width, height=height):
                    lines = frame_to_ascii(frame, width, height, mode)
                    self.assertEqual(len(lines), height)
                    self.assertTrue(all(len(line) == width for line in lines))
                    self.assertTrue(all(" " <= ch <= "~" for line in lines for ch in line))
                    self.assertEqual(lines, frame_to_ascii(frame, width, height, mode))

    def test_flat_white_and_black_keep_original_polarity(self):
        black = np.zeros((12, 10, 3), dtype=np.uint8)
        white = np.full_like(black, 255)
        for mode in ("classic", "dense"):
            with self.subTest(mode=mode):
                self.assertEqual(frame_to_ascii(white, 5, 3, mode), [" " * 5] * 3)
                dark_chars = set("".join(frame_to_ascii(black, 5, 3, mode)))
                self.assertEqual(len(dark_chars), 1)
                self.assertNotIn(" ", dark_chars)

    def test_flat_near_white_becomes_blank_but_light_contours_remain(self):
        frame = np.full((6, 9, 3), (208, 208, 203), dtype=np.uint8)
        frame[:, 3:6] = (203, 203, 198)
        frame[:, 6] = 170
        frame[:, 7:] = 240
        for mode in CHARSETS:
            with self.subTest(mode=mode):
                row, = frame_to_ascii(frame, 3, 1, mode)
                self.assertEqual(row[0], " ")
                self.assertNotEqual(row[1], " ")
                self.assertNotEqual(row[2], " ")

    def test_uniform_gray_regions_stay_uniform(self):
        for level in (25, 45, 55, 128, 220):
            frame = np.full((24, 18, 3), level, dtype=np.uint8)
            for mode in ("classic", "dense"):
                with self.subTest(level=level, mode=mode):
                    lines = frame_to_ascii(frame, 6, 4, mode)
                    self.assertEqual(len(set("".join(lines))), 1)

    def test_faint_shadow_strokes_retain_their_direction(self):
        forward = np.full((60, 30, 3), 55, dtype=np.uint8)
        cv2.line(forward, (27, 4), (2, 55), (25,) * 3, thickness=6)
        backward = np.ascontiguousarray(forward[:, ::-1])
        forward_text = frame_to_ascii(forward, 1, 1, "dense")
        backward_text = frame_to_ascii(backward, 1, 1, "dense")
        self.assertNotEqual(forward_text, backward_text)
        self.assertEqual(forward_text, frame_to_ascii(forward, 1, 1, "dense"))
        self.assertEqual(backward_text, frame_to_ascii(backward, 1, 1, "dense"))

    def test_small_balanced_noise_does_not_replace_a_flat_tone_with_shapes(self):
        # Keep each sample within two gray levels of the same mean. Such codec
        # noise should not trigger contour matching or introduce flicker.
        signs = np.where(np.indices((6, 3)).sum(axis=0) % 2, 1, -1)
        clean = np.full((6, 3, 3), 128, dtype=np.uint8)
        noisy = np.repeat((128 + 2 * signs).astype(np.uint8)[:, :, None], 3, axis=2)
        for mode in ("classic", "dense"):
            with self.subTest(mode=mode):
                expected = frame_to_ascii(clean, 1, 1, mode)
                self.assertEqual(frame_to_ascii(noisy, 1, 1, mode), expected)
                self.assertEqual(frame_to_ascii(noisy[:, ::-1].copy(), 1, 1, mode), expected)
                self.assertEqual(frame_to_ascii(noisy, 1, 1, mode), expected)

    def test_shadow_tone_is_not_clipped_by_unrelated_bright_background(self):
        dark_surround = np.zeros((12, 6, 3), dtype=np.uint8)
        bright_surround = np.full_like(dark_surround, 255)
        dark_surround[:6, :3] = 25
        bright_surround[:6, :3] = 25
        for mode in ("classic", "dense"):
            with self.subTest(mode=mode):
                self.assertEqual(frame_to_ascii(dark_surround, 2, 2, mode)[0][0],
                                 frame_to_ascii(bright_surround, 2, 2, mode)[0][0])

    def test_mirrored_lines_get_different_ascii_diagonals(self):
        # A 30×60 source matches one cell twice as tall as it is wide.
        # Mirroring preserves brightness, changing only shape.
        forward = np.full((60, 30, 3), 255, dtype=np.uint8)
        cv2.line(forward, (27, 4), (2, 55), (0, 0, 0), thickness=6)
        backward = np.ascontiguousarray(forward[:, ::-1])
        for mode in ("classic", "dense"):
            with self.subTest(mode=mode):
                self.assertEqual(frame_to_ascii(forward, 1, 1, mode), ["/"])
                self.assertEqual(frame_to_ascii(backward, 1, 1, mode), ["\\"])

    def test_stylized_modes_keep_original_palettes_and_dimensions(self):
        frame = np.random.default_rng(9).integers(0, 256, (19, 27, 3), dtype=np.uint8)
        for mode, palette in STYLIZED_PALETTES.items():
            for width, height in ((1, 1), (1, 5), (7, 1), (9, 6)):
                with self.subTest(mode=mode, width=width, height=height):
                    lines = frame_to_ascii(frame, width, height, mode)
                    self.assertEqual(len(lines), height)
                    self.assertTrue(all(len(line) == width for line in lines))
                    self.assertLessEqual(set("".join(lines)), set(palette + " "))
                    self.assertEqual(lines, frame_to_ascii(frame, width, height, mode))

    def test_stylized_modes_follow_dark_to_light_palette_order(self):
        for mode, palette in STYLIZED_PALETTES.items():
            with self.subTest(mode=mode):
                palette = palette if " " in palette else palette + " "
                brightness_totals = []
                used_symbols = set()
                for level in range(0, 256, 17):
                    frame = np.full((32, 32, 3), level, dtype=np.uint8)
                    text = "".join(frame_to_ascii(frame, 16, 16, mode))
                    self.assertEqual(len(set(text)), 1, f"flat gray level {level}")
                    used_symbols.update(text)
                    brightness_totals.append(sum(palette.index(ch) for ch in text))
                    if level == 0:
                        self.assertEqual(set(text), {palette[0]})
                    elif level == 255:
                        self.assertEqual(set(text), {palette[-1]})
                self.assertEqual(brightness_totals, sorted(brightness_totals))
                self.assertLessEqual(used_symbols, set(palette))
                self.assertGreaterEqual(len(used_symbols), 3)

    def test_binary_has_both_bits_for_intermediate_tones(self):
        frame = np.full((32, 32, 3), 64, dtype=np.uint8)
        frame[:, 16:] = 192
        lines = frame_to_ascii(frame, 16, 16, "binary")
        self.assertEqual(set("".join(lines)), {"0", "1"})
        self.assertTrue(all(line[0] == "0" and line[-1] == "1" for line in lines))

    def test_stylized_modes_keep_a_narrow_shadow_stripe(self):
        width, height = 16, 8
        uniform = np.full((48, 48, 3), 160, dtype=np.uint8)
        shaded = uniform.copy()
        # The stripe is one pixel wide in a frame scaled to 16 text cells.
        shaded[:, 10] = 100
        stripe_column = 10 * width // shaded.shape[1]
        for mode, palette in STYLIZED_PALETTES.items():
            with self.subTest(mode=mode):
                reference = frame_to_ascii(uniform, width, height, mode)
                with_stripe = frame_to_ascii(shaded, width, height, mode)
                plain_tone = sum(palette.index(row[stripe_column]) for row in reference)
                stripe_tone = sum(palette.index(row[stripe_column]) for row in with_stripe)
                self.assertLess(stripe_tone, plain_tone)

    def test_stylized_mode_background_is_stable_under_small_balanced_noise(self):
        clean = np.full((48, 48, 3), 128, dtype=np.uint8)
        signs = np.where(np.indices((48, 48)).sum(axis=0) % 2, 1, -1)
        noisy = (clean.astype(np.int16) + 2 * signs[:, :, None]).astype(np.uint8)
        for mode in STYLIZED_PALETTES:
            with self.subTest(mode=mode):
                reference = frame_to_ascii(clean, 16, 8, mode)
                self.assertEqual(frame_to_ascii(noisy, 16, 8, mode), reference)
                self.assertEqual(frame_to_ascii(noisy[:, ::-1].copy(), 16, 8, mode), reference)

    def test_cli_offers_only_original_modes(self):
        expected = {"classic", "dense", "blocks", "matrix", "hex", "binary"}
        for command in ("run", "config"):
            with self.subTest(command=command), redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as exit_status:
                    create_parser().parse_args([command, "--help"])
                self.assertEqual(exit_status.exception.code, 0)
                choices = re.search(r"--mode\s+\{([^}]+)\}", output.getvalue())
                self.assertIsNotNone(choices)
                self.assertEqual(set(choices[1].split(",")), expected)


if __name__ == "__main__":
    unittest.main()
