"""The pixels backend: the raster under the text, and the text cleared under
later shapes. Skipped without soft-raster."""

from __future__ import annotations

import unittest

from kilix_pane import deps
from kilix_pane.cells import Rect
from kilix_pane.painter import Painter
from kilix_pane.screen import PixelScreen
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

    def test_pixel_screen_sends_image_then_text(self) -> None:
        out: list[str] = []
        presenter = deps.find("kitty_frame_presenter")
        screen = PixelScreen(out.append, presenter.module if presenter.ok else None)
        p = self.painter()
        p.text(2, 2, "hello", "ink")
        rgb = bytes(p.canvas.rgb_bytes())
        screen.present_frame(rgb, p.canvas.width, p.canvas.height, 20, 6, p.grid)
        frame = out[-1]
        self.assertLess(frame.index("\x1b_G"), frame.index("hello"))
        self.assertIn("z=-1", frame)
        vt = VT(20, 6)
        vt.feed(frame)
        self.assertEqual(vt.images, 1 if presenter.ok else 1)
        self.assertIn("hello", vt.text())
        self.assertIn("a=d,d=I", screen.close())


if __name__ == "__main__":
    unittest.main()
