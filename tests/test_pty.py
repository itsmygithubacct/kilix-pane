"""The runtime on a real pseudo-terminal: modes on, input, resize, clean exit.

These are the guarantees a user notices when they fail: a terminal left in
raw mode, mouse reporting still on, or the alternate screen never left.
"""

from __future__ import annotations

import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def spawn(*args: str, rows: int = 24, columns: int = 80) -> tuple[int, int]:
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    for key in ("KITTY_WINDOW_ID", "KILIX_STREAM", "TMUX", "TERM_PROGRAM"):
        env.pop(key, None)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROOT / "src")] + [p for p in sys.path if p])
    pid, fd = pty.fork()
    if pid == 0:
        os.execvpe(sys.executable, [sys.executable, "-m", "kilix_pane", *args], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
    return pid, fd


def read_until(fd: int, needle: bytes, timeout: float = 10.0) -> bytes:
    out = b""
    deadline = time.monotonic() + timeout
    while needle not in out and time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
    return out


def drain_and_wait(pid: int, fd: int, timeout: float = 10.0) -> tuple[bytes, int]:
    out = b""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            try:
                chunk = os.read(fd, 65536)
                out += chunk
            except OSError:
                pass
        if done:
            return out, status
    os.kill(pid, signal.SIGKILL)
    os.waitpid(pid, 0)
    raise AssertionError("child did not exit")


class RealTerminal(unittest.TestCase):
    def test_modes_on_then_restored_on_quit(self) -> None:
        pid, fd = spawn("demo")
        try:
            start = read_until(fd, b"Water the plants")
            for mode in (b"\x1b[?1049h", b"\x1b[?1006h", b"\x1b[?2004h",
                         b"\x1b[>1u"):
                self.assertIn(mode, start)
            os.write(fd, b"q")
            rest, status = drain_and_wait(pid, fd)
        finally:
            os.close(fd)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        for mode in (b"\x1b[<u", b"\x1b[?1006l", b"\x1b[?2004l", b"\x1b[?1049l",
                     b"\x1b[?25h", b"\x1b[?7h"):
            self.assertIn(mode, rest)

    def test_sigterm_still_restores(self) -> None:
        pid, fd = spawn("demo")
        try:
            read_until(fd, b"Water the plants")
            os.kill(pid, signal.SIGTERM)
            rest, status = drain_and_wait(pid, fd)
        finally:
            os.close(fd)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        self.assertIn(b"\x1b[?1049l", rest)

    def test_resize_redraws_at_the_new_size(self) -> None:
        pid, fd = spawn("demo", columns=80)
        try:
            read_until(fd, b"Water the plants")
            fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 30, 120, 0, 0))
            os.kill(pid, signal.SIGWINCH)
            redraw = read_until(fd, b"\x1b[2J")
            self.assertIn(b"\x1b[2J", redraw)
            os.write(fd, b"\x1b[27u")  # kitty-encoded escape does not quit
            os.write(fd, b"\x03")       # ctrl+c does
            _, status = drain_and_wait(pid, fd)
        finally:
            os.close(fd)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)

    def test_typing_reaches_the_field(self) -> None:
        pid, fd = spawn("demo")
        try:
            read_until(fd, b"Water the plants")
            os.write(fd, b"a")
            time.sleep(0.2)
            os.write(fd, "Zebra café 木\r".encode())
            # The writer skips unchanged cells, so the words arrive as
            # separate runs; each must be there.
            seen = read_until(fd, "café 木".encode())
            self.assertIn(b"Zebra", seen)
            self.assertIn("café 木".encode(), seen)
            os.write(fd, b"\x1b[27u")   # leave the field
            time.sleep(0.2)
            os.write(fd, b"q")
            _, status = drain_and_wait(pid, fd)
        finally:
            os.close(fd)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)


if __name__ == "__main__":
    unittest.main()
