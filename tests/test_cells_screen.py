from __future__ import annotations

import random
import unittest

from kilix_pane.cells import CellGrid, Rect, Style, char_width, clip, control_free, text_width
from kilix_pane.screen import CellScreen, _xterm256, sgr

from vt import VT


class Widths(unittest.TestCase):
    def test_widths(self) -> None:
        self.assertEqual(char_width("a"), 1)
        self.assertEqual(char_width("火"), 2)
        self.assertEqual(char_width("́"), 0)  # combining acute
        self.assertEqual(char_width("\x1b"), 0)
        self.assertEqual(text_width("é火"), 3)

    def test_clip_marks_the_cut_and_respects_wide_chars(self) -> None:
        self.assertEqual(clip("hello", 10), "hello")
        self.assertEqual(clip("hello world", 6), "hello…")
        self.assertEqual(clip("火曜日です", 5), "火曜…")
        self.assertLessEqual(text_width(clip("火曜日です", 4)), 4)
        self.assertEqual(clip("abc", 0), "")

    def test_control_characters_are_never_written(self) -> None:
        self.assertEqual(control_free("a\x1b[31mb\nc\td"), "a [31mb c    d")


class Grid(unittest.TestCase):
    def test_put_keeps_background_and_splits_wide(self) -> None:
        grid = CellGrid(10, 2)
        grid.clear(Rect(0, 0, 10, 1), Style(bg=0x123456))
        used = grid.put(1, 0, "火x", Style(fg=1))
        self.assertEqual(used, 3)
        self.assertEqual(grid.rows[0][1].style.bg, 0x123456)
        self.assertEqual(grid.rows[0][2].char, "")
        grid.put(2, 0, "y", Style())  # overwrite the right half
        self.assertEqual(grid.rows[0][1].char, " ")
        self.assertEqual(grid.text().split("\n")[0], "  yx      ")

    def test_narrow_over_left_half_clears_the_right_half(self) -> None:
        grid = CellGrid(4, 1)
        grid.put(0, 0, "火", Style())
        grid.put(0, 0, "e", Style())
        self.assertEqual([c.char for c in grid.rows[0]], ["e", " ", " ", " "])

    def test_wide_char_never_straddles_the_limit(self) -> None:
        grid = CellGrid(4, 1)
        self.assertEqual(grid.put(2, 0, "火曜", Style()), 2)
        self.assertEqual(grid.put(3, 0, "火", Style()), 0)


class Diff(unittest.TestCase):
    def replay(self, frames: list[CellGrid]) -> VT:
        out: list[str] = []
        screen = CellScreen(out.append)
        vt = VT(frames[0].width, frames[0].height)
        for frame in frames:
            screen.present(frame)
            vt.feed(out.pop())
            self.assertEqual(vt.text(), frame.text())
        return vt

    def test_random_incremental_frames_reconstruct_exactly(self) -> None:
        rng = random.Random(7)
        words = ["todo", "火曜日", "é", "x", "📅", "   ", "done", "─"]
        for _ in range(40):
            frames = []
            for _ in range(6):
                grid = CellGrid(30, 6)
                for _ in range(rng.randint(0, 12)):
                    style = Style(fg=rng.choice([None, 0xFF0000]),
                                  bg=rng.choice([None, 0x00FF00]),
                                  bold=rng.random() < 0.3)
                    grid.put(rng.randint(-2, 29), rng.randint(0, 5),
                             rng.choice(words), style)
                frames.append(grid)
            self.replay(frames)

    def test_unchanged_frame_writes_no_cells(self) -> None:
        out: list[str] = []
        screen = CellScreen(out.append)
        grid = CellGrid(10, 2)
        grid.put(0, 0, "hello", Style())
        screen.present(grid)
        again = CellGrid(10, 2)
        again.put(0, 0, "hello", Style())
        screen.present(again)
        self.assertNotIn("hello", out[1])
        self.assertNotIn("\x1b[1;", out[1])

    def test_cursor_shown_only_when_requested(self) -> None:
        out: list[str] = []
        screen = CellScreen(out.append)
        grid = CellGrid(5, 1)
        grid.cursor = (2, 0)
        screen.present(grid)
        self.assertTrue(out[0].endswith("\x1b[1;3H\x1b[6 q\x1b[?25h"))
        screen.present(CellGrid(5, 1))
        self.assertTrue(out[1].endswith("\x1b[?25l"))


class Colour(unittest.TestCase):
    def test_sgr(self) -> None:
        self.assertEqual(sgr(Style(fg=0x102030, bold=True)),
                         "\x1b[0;1;38;2;16;32;48m")
        self.assertEqual(sgr(Style(bg=0xFFFFFF), truecolor=False),
                         "\x1b[0;48;5;231m")

    def test_xterm256(self) -> None:
        self.assertEqual(_xterm256(0, 0, 0), 16)
        self.assertEqual(_xterm256(128, 128, 128), 244)
        self.assertEqual(_xterm256(255, 0, 0), 196)


if __name__ == "__main__":
    unittest.main()
