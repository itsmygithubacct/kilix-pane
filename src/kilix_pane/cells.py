"""Cell geometry and the cell grid both backends draw text into.

Layout in this package is in terminal cells, never pixels, because text is
always drawn by the terminal: in the pixel backend the raster sits beneath the
text at a negative z-index, so the terminal's own font renders every
character, including the ones an embedded raster font cannot. Pixels only
decorate the cells.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator, NamedTuple

__all__ = [
    "Cell",
    "CellGrid",
    "Rect",
    "char_width",
    "clip",
    "text_width",
]


class Rect(NamedTuple):
    """A rectangle in cells: column, row, width, height. Zero-based."""

    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.right and self.y <= y < self.bottom

    def inset(self, dx: int, dy: int | None = None) -> "Rect":
        dy = dx if dy is None else dy
        return Rect(self.x + dx, self.y + dy,
                    max(0, self.w - 2 * dx), max(0, self.h - 2 * dy))

    def take_top(self, rows: int) -> tuple["Rect", "Rect"]:
        rows = max(0, min(rows, self.h))
        return (Rect(self.x, self.y, self.w, rows),
                Rect(self.x, self.y + rows, self.w, self.h - rows))

    def take_bottom(self, rows: int) -> tuple["Rect", "Rect"]:
        rows = max(0, min(rows, self.h))
        return (Rect(self.x, self.bottom - rows, self.w, rows),
                Rect(self.x, self.y, self.w, self.h - rows))

    def take_left(self, columns: int) -> tuple["Rect", "Rect"]:
        columns = max(0, min(columns, self.w))
        return (Rect(self.x, self.y, columns, self.h),
                Rect(self.x + columns, self.y, self.w - columns, self.h))

    def take_right(self, columns: int) -> tuple["Rect", "Rect"]:
        columns = max(0, min(columns, self.w))
        return (Rect(self.right - columns, self.y, columns, self.h),
                Rect(self.x, self.y, self.w - columns, self.h))

    def intersect(self, other: "Rect") -> "Rect":
        x = max(self.x, other.x)
        y = max(self.y, other.y)
        r = min(self.right, other.right)
        b = min(self.bottom, other.bottom)
        return Rect(x, y, max(0, r - x), max(0, b - y))

    @property
    def empty(self) -> bool:
        return self.w <= 0 or self.h <= 0


@lru_cache(maxsize=4096)
def char_width(char: str) -> int:
    """Columns one character occupies: 0, 1 or 2.

    East Asian Wide and Fullwidth characters take two cells, combining marks
    and format characters none. Ambiguous-width characters are counted as one,
    which is what a terminal in a non-CJK locale does.
    """
    code = ord(char)
    if code < 0x20 or 0x7F <= code < 0xA0:
        return 0
    if unicodedata.combining(char):
        return 0
    category = unicodedata.category(char)
    if category in ("Mn", "Me", "Cf") or code == 0x200B:
        return 0
    if 0x1F1E6 <= code <= 0x1F1FF:  # regional indicators pair into one flag
        return 1
    if unicodedata.east_asian_width(char) in ("W", "F"):
        return 2
    return 1


def text_width(text: str) -> int:
    return sum(char_width(c) for c in text)


def clip(text: str, width: int, ellipsis: str = "…") -> str:
    """`text` cut to at most `width` columns, marked when it was cut."""
    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text
    room = width - text_width(ellipsis)
    out, used = [], 0
    for char in text:
        w = char_width(char)
        if used + w > room:
            break
        out.append(char)
        used += w
    return "".join(out) + (ellipsis if room >= 0 else "")


def control_free(text: str) -> str:
    """Text safe to write to a terminal: controls become spaces, tabs four.

    Everything that reaches a cell passes through here, so a task title
    containing an escape sequence is shown, never executed.
    """
    out = []
    for char in text:
        code = ord(char)
        if char == "\t":
            out.append("    ")
        elif code < 0x20 or 0x7F <= code < 0xA0 or code in (0x2028, 0x2029):
            out.append(" ")
        else:
            out.append(char)
    return "".join(out)


@dataclass(frozen=True)
class Style:
    """How a cell's text is drawn. Colours are 0xRRGGBB, or None for the
    terminal's default."""

    fg: int | None = None
    bg: int | None = None
    bold: bool = False
    dim: bool = False
    italic: bool = False
    underline: bool = False
    strike: bool = False
    reverse: bool = False


PLAIN = Style()


class Cell(NamedTuple):
    char: str  # "" marks the right half of a wide character
    style: Style


BLANK = Cell(" ", PLAIN)


class CellGrid:
    """A screen of cells. The backends draw into one and diff two."""

    def __init__(self, width: int, height: int) -> None:
        self.width = max(0, width)
        self.height = max(0, height)
        self.rows: list[list[Cell]] = [
            [BLANK] * self.width for _ in range(self.height)
        ]
        #: Where the terminal cursor should be shown, or None to hide it.
        self.cursor: tuple[int, int] | None = None

    def clear(self, rect: Rect | None = None, style: Style = PLAIN) -> None:
        rect = Rect(0, 0, self.width, self.height) if rect is None else rect
        rect = rect.intersect(Rect(0, 0, self.width, self.height))
        blank = Cell(" ", style)
        for y in range(rect.y, rect.bottom):
            row = self.rows[y]
            self._split_wide(row, rect.x)
            self._split_wide(row, rect.right)
            row[rect.x:rect.right] = [blank] * rect.w

    def background(self, x: int, y: int) -> int | None:
        if 0 <= y < self.height and 0 <= x < self.width:
            return self.rows[y][x].style.bg
        return None

    @staticmethod
    def _split_wide(row: list[Cell], x: int) -> None:
        """Writing at x must not leave half of a wide character behind."""
        if 0 < x < len(row) and row[x].char == "":
            row[x - 1] = Cell(" ", row[x - 1].style)
            row[x] = Cell(" ", row[x].style)

    def put(self, x: int, y: int, text: str, style: Style,
            limit: int | None = None, keep_bg: bool = True) -> int:
        """Write `text` from (x, y); return the columns used.

        `limit` is an exclusive right edge. With `keep_bg` each cell keeps
        the background already painted there, which is how text sits on a
        filled panel without knowing its colour.
        """
        if not 0 <= y < self.height:
            return 0
        right = self.width if limit is None else min(self.width, limit)
        row = self.rows[y]
        column = x
        for char in control_free(text):
            w = char_width(char)
            if w == 0:
                continue
            if column + w > right:
                break
            if column >= 0:
                # Neither neighbour may be left holding half of a wide
                # character this write overlaps.
                self._split_wide(row, column)
                self._split_wide(row, column + w)
                cell_style = style
                if keep_bg and style.bg is None:
                    cell_style = _with_bg(style, row[column].style.bg)
                row[column] = Cell(char, cell_style)
                if w == 2:
                    row[column + 1] = Cell("", cell_style)
            column += w
        return max(0, column - x)

    def text(self) -> str:
        """The grid as plain text, one line per row, trailing spaces kept."""
        return "\n".join(
            "".join(cell.char for cell in row) for row in self.rows
        )

    def lines(self) -> list[str]:
        return [line.rstrip() for line in self.text().split("\n")]

    def __iter__(self) -> Iterator[list[Cell]]:
        return iter(self.rows)


@lru_cache(maxsize=1024)
def _with_bg(style: Style, bg: int | None) -> Style:
    if style.bg == bg:
        return style
    return Style(style.fg, bg, style.bold, style.dim, style.italic,
                 style.underline, style.strike, style.reverse)
