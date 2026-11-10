"""Turning a painted frame into terminal output.

`CellScreen` writes the difference between the previous grid and the new
one: cursor moves and SGR runs for the cells that changed, nothing else.
`PixelScreen` does the same for the text and hands the raster to
`kitty-frame-presenter`, which updates the placed image in place with damage
rectangles. Without the presenter it falls back to one compressed inline
placement per frame, which is correct but heavier.
"""

from __future__ import annotations

import base64
import os
import zlib
from typing import Any

from .cells import BLANK, CellGrid, Style

__all__ = ["CellScreen", "PixelScreen", "sgr"]

IMAGE_ID = 0x4B50  # "KP"


def sgr(style: Style, truecolor: bool = True) -> str:
    """The SGR sequence that selects `style` from a reset state."""
    parts = ["0"]
    if style.bold:
        parts.append("1")
    if style.dim:
        parts.append("2")
    if style.italic:
        parts.append("3")
    if style.underline:
        parts.append("4")
    if style.reverse:
        parts.append("7")
    if style.strike:
        parts.append("9")
    if style.fg is not None:
        parts.append(_colour(38, style.fg, truecolor))
    if style.bg is not None:
        parts.append(_colour(48, style.bg, truecolor))
    return "\x1b[" + ";".join(parts) + "m"


def _colour(base: int, rgb: int, truecolor: bool) -> str:
    r, g, b = (rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255
    if truecolor:
        return f"{base};2;{r};{g};{b}"
    return f"{base};5;{_xterm256(r, g, b)}"


def _xterm256(r: int, g: int, b: int) -> int:
    def level(v: int) -> int:
        return 0 if v < 48 else 1 if v < 115 else (v - 35) // 40

    lr, lg, lb = level(r), level(g), level(b)
    cube = 16 + 36 * lr + 6 * lg + lb
    grey = round((r + g + b) / 3)
    grey_index = 232 + max(0, min(23, (grey - 8) // 10))
    steps = [0, 95, 135, 175, 215, 255]
    cube_rgb = (steps[lr], steps[lg], steps[lb])
    grey_rgb = (8 + 10 * (grey_index - 232),) * 3

    def distance(c: tuple[int, ...]) -> int:
        return (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2

    return cube if distance(cube_rgb) <= distance(grey_rgb) else grey_index


def truecolor_supported(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    if env.get("COLORTERM", "").lower() in ("truecolor", "24bit"):
        return True
    term = env.get("TERM", "")
    return "kitty" in term or "direct" in term or bool(env.get("KITTY_WINDOW_ID"))


class CellScreen:
    def __init__(self, write: Any, *, truecolor: bool | None = None) -> None:
        self.write = write
        self.truecolor = truecolor_supported() if truecolor is None else truecolor
        self.previous: CellGrid | None = None

    def invalidate(self) -> None:
        self.previous = None

    def clears(self, grid: CellGrid) -> bool:
        """Whether `diff(grid)` will start by clearing the whole screen."""
        previous = self.previous
        return (previous is None or previous.width != grid.width
                or previous.height != grid.height)

    def diff(self, grid: CellGrid) -> str:
        """Output that turns the previous frame into `grid`."""
        out: list[str] = []
        previous = self.previous
        full = self.clears(grid)
        if full:
            out.append("\x1b[0m\x1b[2J")
        current: Style | None = None
        for y, row in enumerate(grid.rows):
            old = None if full else previous.rows[y]  # type: ignore[union-attr]

            def changed(x: int) -> bool:
                return row[x] != (BLANK if old is None else old[x])

            x = 0
            while x < grid.width:
                if not changed(x):
                    x += 1
                    continue
                if row[x].char == "" and x > 0:
                    x -= 1  # repaint the whole wide character
                out.append(f"\x1b[{y + 1};{x + 1}H")
                while x < grid.width and (changed(x) or row[x].char == ""):
                    cell = row[x]
                    if cell.char:
                        if cell.style != current:
                            out.append(sgr(cell.style, self.truecolor))
                            current = cell.style
                        out.append(cell.char)
                    x += 1
        out.append("\x1b[0m")
        if grid.cursor is not None:
            cx, cy = grid.cursor
            out.append(f"\x1b[{cy + 1};{cx + 1}H\x1b[6 q\x1b[?25h")
        else:
            out.append("\x1b[?25l")
        self.previous = grid
        return "".join(out)

    def present(self, grid: CellGrid) -> None:
        self.write(self.diff(grid))


class _Collector:
    """A `write(str)` sink for the presenter, flushed with the frame."""

    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, value: str) -> int:
        self.parts.append(value)
        return len(value)

    def take(self) -> str:
        out = "".join(self.parts)
        self.parts.clear()
        return out


class PixelScreen(CellScreen):
    def __init__(self, write: Any, presenter_module: Any = None, *,
                 truecolor: bool | None = None, max_fps: float = 60) -> None:
        super().__init__(write, truecolor=truecolor)
        self._sink = _Collector()
        self.presenter = None
        if presenter_module is not None:
            self.presenter = presenter_module.FramePresenter(
                self._sink, image_id=IMAGE_ID, max_fps=max_fps)

    def invalidate(self) -> None:
        super().invalidate()
        if self.presenter is not None:
            self.presenter.invalidate()

    def present_frame(self, rgb: bytes, width: int, height: int,
                      columns: int, rows: int, grid: CellGrid) -> None:
        # ED 2 deletes every image placement (kitty's screen_erase_in_display
        # calls grman_clear), so a repaint that clears the screen goes out
        # before the image, and the presenter must place a whole new image
        # rather than edit the one the clear just deleted.
        clears = self.clears(grid)
        if clears and self.presenter is not None:
            self.presenter.invalidate()
        text = self.diff(grid)
        image = ""
        if self.presenter is not None:
            self.presenter.present(rgb, width, height, columns, rows)
            self.presenter.flush()
            image = self._sink.take()
        else:
            image = _direct_placement(rgb, width, height, columns, rows)
        image = "\x1b7" + image + "\x1b8"
        # Otherwise the image first, then the text that sits on it: one write,
        # so the terminal never shows a frame's text over the previous art.
        self.write(text + image if clears else image + text)

    def flush(self) -> None:
        """Release a frame the presenter's pacing held back."""
        if self.presenter is not None:
            self.presenter.flush()
            pending = self._sink.take()
            if pending:
                self.write("\x1b7" + pending + "\x1b8")

    def close(self) -> str:
        if self.presenter is not None:
            self.presenter.close()
        return f"\x1b_Ga=d,d=I,i={IMAGE_ID},q=2\x1b\\"


def _direct_placement(rgb: bytes, width: int, height: int,
                      columns: int, rows: int) -> str:
    payload = base64.b64encode(zlib.compress(rgb, 1))
    out = ["\x1b[1;1H"]
    first = True
    while True:
        piece, payload = payload[:4096], payload[4096:]
        more = 1 if payload else 0
        if first:
            control = (f"a=T,i={IMAGE_ID},p=1,z=-1,f=24,o=z,s={width},"
                       f"v={height},c={columns},r={rows},C=1,q=2,m={more}")
            first = False
        else:
            control = f"m={more}"
        out.append(f"\x1b_G{control};{piece.decode('ascii')}\x1b\\")
        if not more:
            break
    return "".join(out)
