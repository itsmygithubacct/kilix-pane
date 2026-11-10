"""One drawing API, two looks.

Widgets draw through a `Painter` in cell coordinates. In **cells** mode every
operation becomes characters and colours in a `CellGrid`, which works in any
terminal, over SSH and inside tmux. In **pixels** mode the shapes are drawn
by soft-raster into a frame the presenter places *beneath* the text
(``z=-1``), and only the text goes into the grid: rounded panels, real
check marks and anti-aliased bars, with every character still rendered by the
terminal's own font. The same widget code produces both.

Ordering matters in pixels mode because the terminal always draws text above
the image: a panel painted over earlier text must also blank those cells, or
the text would show through it. `fill` and `panel` do that.
"""

from __future__ import annotations

from typing import Any

from .cells import CellGrid, Rect, Style, clip, text_width
from .theme import Theme

__all__ = ["Painter"]

_EIGHTHS = " ▏▎▍▌▋▊▉█"


class Painter:
    def __init__(
        self,
        width: int,
        height: int,
        theme: Theme,
        *,
        canvas: Any = None,
        cell_size: tuple[int, int] = (8, 16),
    ) -> None:
        self.width = width
        self.height = height
        self.theme = theme
        self.grid = CellGrid(width, height)
        #: soft-raster Canvas in pixels mode, None in cells mode.
        self.canvas = canvas
        self.cw, self.ch = cell_size
        self.cursor: tuple[int, int] | None = None

    @property
    def pixels(self) -> bool:
        return self.canvas is not None

    @property
    def bounds(self) -> Rect:
        return Rect(0, 0, self.width, self.height)

    # ------------------------------------------------------------- helpers

    def _px(self, rect: Rect) -> tuple[float, float, float, float]:
        return (rect.x * self.cw, rect.y * self.ch,
                rect.w * self.cw, rect.h * self.ch)

    def _style(self, role: str | None, **flags: bool) -> Style:
        fg = self.theme[role] if role else None
        return Style(fg=fg, **flags)

    # --------------------------------------------------------- primitives

    def fill(self, rect: Rect, role: str) -> None:
        """A flat rectangle of `role`. Clears any text beneath it."""
        rect = rect.intersect(self.bounds)
        if rect.empty:
            return
        colour = self.theme[role]
        if self.canvas is not None:
            self.canvas.fill_rect(*self._px(rect), colour)
            self.grid.clear(rect)
        else:
            self.grid.clear(rect, Style(bg=colour))

    def panel(self, rect: Rect, role: str = "panel",
              edge: str | None = "panel_edge", radius: float = 0.6) -> None:
        """A raised card. Rounded with an outline in pixels; flat in cells."""
        rect = rect.intersect(self.bounds)
        if rect.empty:
            return
        if self.canvas is None:
            self.fill(rect, role)
            return
        x, y, w, h = self._px(rect)
        r = min(self.ch * radius, w / 2, h / 2)
        self.canvas.fill_round_rect(x + 1, y + 1, w - 2, h - 2, r,
                                    self.theme[role])
        if edge:
            self.canvas.stroke_round_rect(x + 1, y + 1, w - 2, h - 2, r, 1.0,
                                          self.theme[edge])
        self.grid.clear(rect)

    def highlight(self, rect: Rect, role: str = "selection") -> None:
        """A row highlight: a pill in pixels, a background band in cells."""
        rect = rect.intersect(self.bounds)
        if rect.empty:
            return
        if self.canvas is None:
            self.fill(rect, role)
            return
        x, y, w, h = self._px(rect)
        r = min(self.ch * 0.35, h / 2)
        self.canvas.fill_round_rect(x + 2, y + 1, w - 4, h - 2, r,
                                    self.theme[role])
        self.grid.clear(rect)

    def ring(self, rect: Rect, role: str = "accent") -> None:
        """A focus outline. Pixels only: in cells the highlight carries it."""
        rect = rect.intersect(self.bounds)
        if self.canvas is None or rect.empty:
            return
        x, y, w, h = self._px(rect)
        r = min(self.ch * 0.35, h / 2)
        self.canvas.stroke_round_rect(x + 2, y + 1, w - 4, h - 2, r, 1.5,
                                      self.theme[role])

    def text(self, x: int, y: int, text: str, role: str = "ink", *,
             limit: int | None = None, bold: bool = False, dim: bool = False,
             italic: bool = False, underline: bool = False,
             strike: bool = False, ellipsis: bool = True) -> int:
        """Draw text from (x, y); return the columns used.

        `limit` is an exclusive right edge; text that does not fit is cut and
        marked with an ellipsis unless `ellipsis` is False.
        """
        right = self.width if limit is None else min(limit, self.width)
        if ellipsis:
            text = clip(text, right - x)
        style = self._style(role, bold=bold, dim=dim, italic=italic,
                            underline=underline, strike=strike)
        return self.grid.put(x, y, text, style, limit=right)

    def rule(self, x: int, y: int, w: int, role: str = "panel_edge") -> None:
        """A horizontal divider through the middle of a row."""
        if w <= 0 or not 0 <= y < self.height:
            return
        if self.canvas is not None:
            py = y * self.ch + self.ch // 2
            self.canvas.fill_rect(x * self.cw, py, w * self.cw, 1,
                                  self.theme[role])
        else:
            self.grid.put(x, y, "─" * w, self._style(role))

    def vrule(self, x: int, y: int, h: int, role: str = "panel_edge") -> None:
        if h <= 0:
            return
        if self.canvas is not None:
            px = x * self.cw + self.cw // 2
            self.canvas.fill_rect(px, y * self.ch, 1, h * self.ch,
                                  self.theme[role])
        else:
            for row in range(y, y + h):
                self.grid.put(x, row, "│", self._style(role))

    def check(self, x: int, y: int, checked: bool, role: str = "accent",
              box_role: str = "ink_faint") -> int:
        """A checkbox occupying three columns. Returns 3."""
        if self.canvas is not None:
            cx = (x + 1.5) * self.cw
            cy = (y + 0.5) * self.ch
            radius = min(self.ch * 0.36, self.cw * 1.4)
            if checked:
                self.canvas.fill_circle(cx, cy, radius, self.theme[role])
                ink = self.theme["ink_invert"]
                s = radius * 0.55
                self.canvas.line(cx - s, cy, cx - s * 0.25, cy + s * 0.7,
                                 max(1.5, radius * 0.22), ink)
                self.canvas.line(cx - s * 0.25, cy + s * 0.7, cx + s,
                                 cy - s * 0.6, max(1.5, radius * 0.22), ink)
            else:
                self.canvas.ring(cx, cy, radius, max(1.2, radius * 0.14),
                                 self.theme[box_role])
            self.grid.clear(Rect(x, y, 3, 1))
        else:
            if checked:
                self.grid.put(x, y, "[✓]", self._style(role, bold=True))
            else:
                self.grid.put(x, y, "[ ]", self._style(box_role))
        return 3

    def dot(self, x: int, y: int, role: str) -> None:
        """A status dot in one column."""
        if self.canvas is not None:
            self.canvas.fill_circle((x + 0.5) * self.cw, (y + 0.5) * self.ch,
                                    min(self.cw, self.ch) * 0.3,
                                    self.theme[role])
            self.grid.clear(Rect(x, y, 1, 1))
        else:
            self.grid.put(x, y, "●", self._style(role))

    def stripe(self, x: int, y: int, h: int, role: str) -> None:
        """A thin vertical colour bar at the left of a row (priority marks)."""
        if self.canvas is not None:
            self.canvas.fill_round_rect(x * self.cw + 2, y * self.ch + 3,
                                        3, h * self.ch - 6, 1.5,
                                        self.theme[role])
        else:
            for row in range(y, y + h):
                self.grid.put(x, row, "▌", self._style(role))

    def bar(self, rect: Rect, fraction: float, role: str = "accent",
            track: str = "field") -> None:
        """A progress bar filled to `fraction` (0..1)."""
        fraction = max(0.0, min(1.0, fraction))
        rect = rect.intersect(self.bounds)
        if rect.empty:
            return
        if self.canvas is not None:
            x, y, w, h = self._px(rect)
            bh = max(4.0, self.ch * 0.35)
            by = y + (h - bh) / 2
            self.canvas.fill_round_rect(x, by, w, bh, bh / 2, self.theme[track])
            if fraction > 0:
                self.canvas.fill_round_rect(x, by, max(bh, w * fraction), bh,
                                            bh / 2, self.theme[role])
            self.grid.clear(rect)
            return
        total = rect.w * 8
        filled = round(total * fraction)
        full, part = divmod(filled, 8)
        text = "█" * full + (_EIGHTHS[part] if part else "")
        style = Style(fg=self.theme[role], bg=self.theme[track])
        self.grid.clear(rect, Style(bg=self.theme[track]))
        self.grid.put(rect.x, rect.y, text, style, limit=rect.right)

    def chip(self, x: int, y: int, label: str, role: str = "tag",
             ink: str = "ink", limit: int | None = None) -> int:
        """A rounded label. Returns the columns used, padding included."""
        right = self.width if limit is None else limit
        label = clip(label, right - x - 2)
        if not label:
            return 0
        w = text_width(label) + 2
        rect = Rect(x, y, w, 1)
        if self.canvas is not None:
            px, py, pw, ph = self._px(rect)
            self.canvas.fill_round_rect(px + 1, py + 2, pw - 2, ph - 4,
                                        (ph - 4) / 2, self.theme[role])
            self.grid.clear(rect)
        else:
            self.grid.clear(rect, Style(bg=self.theme[role]))
        self.grid.put(x + 1, y, label, self._style(ink))
        return w

    def show_cursor(self, x: int, y: int) -> None:
        """Place the terminal's own text cursor here (an input's caret)."""
        if 0 <= x < self.width and 0 <= y < self.height:
            self.cursor = (x, y)
            self.grid.cursor = (x, y)
