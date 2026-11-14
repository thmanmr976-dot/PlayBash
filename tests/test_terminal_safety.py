"""Exercise the real decoder and keyboard cleanup inside isolated PTYs."""
import fcntl
import os
from pathlib import Path
import pty
import re
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest

import cv2
import numpy as np

REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name == 'posix', 'POSIX terminal required')
class TerminalSafetyTests(unittest.TestCase):
    def test_ascii_playback_restores_terminal_after_every_exit(self):
        with tempfile.TemporaryDirectory(prefix='playbash-terminal-') as directory:
            video = str(Path(directory) / 'shapes.avi')
            writer = cv2.VideoWriter(video, cv2.VideoWriter_fourcc(*'MJPG'), 30, (160, 96))
            self.assertTrue(writer.isOpened())
            try:
                for index in range(60):
                    frame = np.zeros((96, 160, 3), dtype=np.uint8)
                    cv2.rectangle(frame, (5, 5), (155, 91), (90, 90, 90), 2)
                    cv2.circle(frame, (25 + index, 48), 15, (210, 210, 210), -1)
                    writer.write(frame)
            finally:
                writer.release()
            for scenario in ('end', 'q', 'color', 'interrupt', 'early_interrupt', 'error',
                             'resize', 'loop', 'slow_fps', 'decoder_wait'):
                with self.subTest(scenario=scenario):
                    self.run_scenario(video, scenario)

    def run_scenario(self, video, scenario):
        master, slave = pty.openpty()
        before = termios.tcgetattr(slave)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
        code = (
            'import playbash.core.player as p\n'
            f'p.load_settings = lambda: {{"hide_cursor": True, "clear_on_exit": True, '
            f'"loop": {scenario == "loop"}, "color": {scenario == "color"}}}\n'
        )
        if scenario == 'error':
            code += 'p.render = lambda frame: (_ for _ in ()).throw(RuntimeError("decode test"))\n'
        if scenario == 'decoder_wait':
            code += (
                'import subprocess, sys\n'
                'import numpy as np\n'
                'from playbash.core.video import FFmpegCapture\n'
                'def open_stalled(path, *, keyboard):\n'
                '    capture = FFmpegCapture.__new__(FFmpegCapture)\n'
                '    capture.keyboard = keyboard\n'
                '    capture.width, capture.height = 160, 96\n'
                '    capture.process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(10)"],\n'
                '                                        stdout=subprocess.PIPE, bufsize=0)\n'
                '    return capture, np.zeros((96, 160, 3), dtype=np.uint8)\n'
                'p.open_video = open_stalled\n'
            )
        fps = 0.2 if scenario == 'slow_fps' else 60
        code += f'p.play({video!r}, mode="dense", fps={fps})\n'
        environment = dict(os.environ, PYTHONPATH=str(REPO), PYTHONDONTWRITEBYTECODE='1')
        proc = subprocess.Popen([sys.executable, '-c', code], cwd=REPO, env=environment,
                                stdin=slave, stdout=slave, stderr=slave, start_new_session=True)
        output = bytearray()
        acted = False
        deadline = time.monotonic() + 12
        try:
            while proc.poll() is None and time.monotonic() < deadline:
                if select.select([master], [], [], 0.05)[0]:
                    output.extend(os.read(master, 65536))
                ready = b'\x1b[?25l' in output if scenario == 'early_interrupt' else b'\x1b[H' in output
                if scenario == 'loop':
                    ready = output.count(b'\x1b[H') > 60
                if ready and not acted:
                    if scenario in ('slow_fps', 'decoder_wait'):
                        # Enter the frame wait, then send q in the same input
                        # burst as unrelated keys. A second keypress must not be needed.
                        time.sleep(0.08)
                        os.write(master, b'x\x1b[Aq')
                        deadline = time.monotonic() + 0.75
                    elif scenario in ('q', 'loop', 'color'):
                        os.write(master, b'q')
                    elif scenario in ('interrupt', 'early_interrupt'):
                        proc.send_signal(signal.SIGINT)
                    elif scenario == 'resize':
                        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 12, 40, 0, 0))
                    acted = True
            self.assertIsNotNone(proc.poll(), 'playback did not finish')
            proc.wait(timeout=1)
            while select.select([master], [], [], 0)[0]:
                output.extend(os.read(master, 65536))
            self.assertEqual(termios.tcgetattr(slave), before)
            self.assertIn(b'\x1b[?25l', output)
            self.assertGreater(output.rfind(b'\x1b[?25h'), output.rfind(b'\x1b[?25l'))
            if scenario == 'color':
                self.assertIn(b'\x1b[38;2;', output)
                self.assertGreater(output.rfind(b'\x1b[39m'), output.rfind(b'\x1b[38;'))
            else:
                self.assertNotIn(b'\x1b[38;', output)
            self.assertNotIn(b'\x1b[48;', output)
            if scenario in ('end', 'q', 'resize', 'loop', 'color', 'slow_fps', 'decoder_wait'):
                self.assertEqual(proc.returncode, 0, output[-1000:].decode(errors='replace'))
                self.assertTrue(acted, 'no frame was rendered')
                plain = re.sub(rb'\x1b\[(?:38;2;\d+;\d+;\d+|39)m', b'', output)
                frames = [part.partition(b'\x1b')[0] for part in plain.split(b'\x1b[H')[1:]]
                self.assertTrue(any(frame.strip() for frame in frames))
                self.assertTrue(all(byte in (10, 13) or 32 <= byte <= 126
                                    for frame in frames for byte in frame))
            elif scenario == 'error':
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(b'decode test', output)
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            os.close(master)
            os.close(slave)
