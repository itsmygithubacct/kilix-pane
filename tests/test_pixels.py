"""The pixels backend: the raster under the text, and the text cleared under
later shapes. Skipped without soft-raster."""

from __future__ import annotations

import unittest

from kilix_pane import deps
from kilix_pane.cells import Rect
from kilix_pane.painter import Painter
from kilix_pane.screen import IMAGE_ID, PixelScreen
from kilix_pane.theme import DARK

from vt import VT

LIBRARY, WHY = deps.soft_raster_library()


@unittest.skipIf(LIBRARY is None, f"soft-raster unavailable: {WHY}")
class Pixels(unittest.TestCase):
    def painter(self, columns: int = 20, rows: int = 6) -> Painter:
        sr = deps.find("soft_raster").module
        canvas = sr.Canvas(columns * 8, rows * 16)
        canvas.clear(DARK["surface"])
        self.addCleanup(canvas.close)
        return Painter(columns, rows, DARK, canvas=canvas, cell_size=(8, 16))

    def pixel(self, painter: Painter, x: float, y: float) -> int:
        rgb = painter.canvas.rgb_bytes()
        offset = (int(y) * painter.canvas.width + int(x)) * 3
        return int.from_bytes(bytes(rgb[offset:offset + 3]), "big")

    def test_panel_hides_text_drawn_before_it(self) -> None:
        p = self.painter()
        p.text(1, 1, "beneath", "ink")
        p.panel(Rect(0, 0, 20, 4))
        self.assertNotIn("beneath", p.grid.text())
        self.assertEqual(self.pixel(p, 80, 32), DARK["panel"])

    def test_text_cells_carry_no_background(self) -> None:
        p = self.painter()
        p.fill(Rect(0, 0, 20, 6), "sidebar")
        p.text(0, 0, "x", "ink")
        self.assertIsNone(p.grid.rows[0][0].style.bg)

    def test_check_mark_is_drawn_in_pixels(self) -> None:
        p = self.painter()
        p.check(0, 0, True)
        self.assertEqual(p.grid.rows[0][1].char, " ")
        centre = self.pixel(p, 1.5 * 8 + 4, 8 - 4)
        self.assertNotEqual(centre, DARK["surface"])

    def test_pixel_screen_orders_clear_image_text(self) -> None:
        # A repaint that clears goes before the image (the clear deletes
        # placements); afterwards the image goes before the text on it.
        out: list[str] = []
        presenter = deps.find("kitty_frame_presenter")
        screen = PixelScreen(out.append, presenter.module if presenter.ok else None,
                             max_fps=0)
        vt = VT(20, 6)
        for word, left in (("hello", 0), ("WORLD", 5)):
            p = self.painter()
            p.panel(Rect(left, 0, 6, 4))
            p.text(2, 2, word, "ink")
            rgb = bytes(p.canvas.rgb_bytes())
            screen.present_frame(rgb, p.canvas.width, p.canvas.height, 20, 6, p.grid)
            vt.feed(out[-1])
            self.assertIn(word, vt.text())
        first, second = out
        self.assertLess(first.index("\x1b[2J"), first.index("\x1b_G"))
        self.assertIn("z=-1", first)
        self.assertNotIn("\x1b[2J", second)
        self.assertLess(second.index("\x1b_G"), second.index("WORLD"))
        self.assertEqual(vt.placements, {str(IMAGE_ID)})
        self.assertIn("a=d,d=I", screen.close())

    def test_image_survives_every_repaint(self) -> None:
        # ED 2 deletes image placements. A first frame, an edit, a repaint
        # after invalidate and a resize must each leave the image placed, and
        # no frame edit may go to an image the clear deleted.
        presenter = deps.find("kitty_frame_presenter")
        for module in ((presenter.module, None) if presenter.ok else (None,)):
            with self.subTest(presenter=module is not None):
                out: list[str] = []
                screen = PixelScreen(out.append, module, max_fps=0)
                self.addCleanup(screen.close)
                vt = VT(24, 8)

                def frame(columns: int, rows: int, word: str) -> None:
                    p = self.painter(columns, rows)
                    p.panel(Rect(1, 1, 10, 3))
                    p.text(2, 2, word, "ink")
                    screen.present_frame(bytes(p.canvas.rgb_bytes()), p.canvas.width,
                                         p.canvas.height, columns, rows, p.grid)
                    vt.feed(out[-1])
                    self.assertIn(word, vt.text())
                    self.assertEqual(vt.placements, {str(IMAGE_ID)}, word)
                    self.assertEqual(vt.lost_edits, 0, word)

                frame(20, 6, "first")
                frame(20, 6, "edited")
                screen.invalidate()
                frame(20, 6, "again")
                frame(24, 8, "resized")


if __name__ == "__main__":
    unittest.main()
