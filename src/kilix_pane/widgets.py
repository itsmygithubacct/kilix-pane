"""The widgets two kinds of application need: lists, fields, buttons, dialogs.

Each widget keeps its own state, draws into a `Painter` inside a `Rect` it
is given, and turns events into a small vocabulary of results ("activate",
"submit", "cancel", an action name). Layout stays with the application.
Every widget records the rectangles it drew, so a mouse event is hit-tested
against exactly what is on screen.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from . import deps
from .cells import Rect, char_width, clip, text_width
from .painter import Painter

__all__ = [
    "Button",
    "ButtonRow",
    "ConfirmDialog",
    "Field",
    "FormDialog",
    "HelpOverlay",
    "LineEdit",
    "ListView",
    "chord",
    "is_click",
    "mouse",
]

DOUBLE_CLICK = 0.4


def _ki() -> Any:
    return deps.find("kitty_input").module


def chord(event: Any) -> str | None:
    """The normalised chord of a pressed key (``"ctrl+s"``, ``"up"``,
    ``"a"``), or None for anything else, including key releases."""
    ki = _ki()
    if ki is not None and isinstance(event, ki.KeyEvent) and event.pressed:
        return event.chord
    return None


def typed_text(event: Any) -> str:
    """Text a key press inserts, if any (no text for ctrl/alt chords)."""
    ki = _ki()
    if ki is None or not isinstance(event, ki.KeyEvent) or not event.pressed:
        return ""
    if event.modifiers & (ki.keys.CTRL | ki.keys.ALT | ki.keys.SUPER):
        return ""
    return event.text


def mouse(event: Any) -> Any:
    ki = _ki()
    return event if ki is not None and isinstance(event, ki.MouseEvent) else None


def is_click(event: Any) -> bool:
    ki = _ki()
    m = mouse(event)
    return m is not None and m.action == ki.MOUSE_PRESS and m.button == 1


def wheel(event: Any) -> int:
    ki = _ki()
    m = mouse(event)
    if m is not None and m.action == ki.MOUSE_WHEEL:
        return m.wheel_y
    return 0


# ---------------------------------------------------------------- list view


class ListView:
    """A scrolling, selectable list drawn one item per `row_height` rows."""

    def __init__(self, row_height: int = 1) -> None:
        self.row_height = max(1, row_height)
        self.count = 0
        self.selected = 0
        self.top = 0
        self.hovered: int | None = None
        self.rect = Rect(0, 0, 0, 0)
        self._last_click: tuple[float, int] = (0.0, -1)

    @property
    def visible(self) -> int:
        return max(1, self.rect.h // self.row_height)

    def set_count(self, count: int) -> None:
        self.count = max(0, count)
        if self.count == 0:
            self.selected = 0
            self.top = 0
        else:
            self.selected = min(self.selected, self.count - 1)
        self.ensure_visible()

    def select(self, index: int) -> None:
        if self.count:
            self.selected = max(0, min(self.count - 1, index))
            self.ensure_visible()

    def ensure_visible(self) -> None:
        if self.selected < self.top:
            self.top = self.selected
        elif self.selected >= self.top + self.visible:
            self.top = self.selected - self.visible + 1
        self.top = max(0, min(self.top, max(0, self.count - self.visible)))

    def at(self, x: int, y: int) -> int | None:
        if not self.rect.contains(x, y):
            return None
        index = self.top + (y - self.rect.y) // self.row_height
        return index if index < self.count else None

    def handle(self, event: Any) -> str | None:
        """'select' (moved), 'activate' (enter / double click), or None."""
        key = chord(event)
        if key is not None:
            moves = {"up": -1, "k": -1, "down": 1, "j": 1,
                     "page_up": -self.visible, "page_down": self.visible}
            if key in moves and self.count:
                self.select(self.selected + moves[key])
                return "select"
            if key in ("home", "g") and self.count:
                self.select(0)
                return "select"
            if key in ("end", "G", "shift+g") and self.count:
                self.select(self.count - 1)
                return "select"
            if key == "enter" and self.count:
                return "activate"
            return None
        m = mouse(event)
        if m is None:
            return None
        ki = _ki()
        if m.action == ki.MOUSE_WHEEL and self.rect.contains(m.x, m.y):
            self.top = max(0, min(self.top + 3 * m.wheel_y,
                                  max(0, self.count - self.visible)))
            return "scroll"
        if m.action == ki.MOUSE_MOVE:
            self.hovered = self.at(m.x, m.y)
            return None
        if is_click(event):
            index = self.at(m.x, m.y)
            if index is None:
                return None
            now = time.monotonic()
            last_time, last_index = self._last_click
            self._last_click = (now, index)
            self.selected = index
            if last_index == index and now - last_time < DOUBLE_CLICK:
                self._last_click = (0.0, -1)
                return "activate"
            return "select"
        return None

    def render(self, painter: Painter, rect: Rect,
               draw: Callable[[Painter, int, Rect, bool, bool], None],
               *, focused: bool = True) -> None:
        self.rect = rect
        self.ensure_visible()
        for slot in range(self.visible):
            index = self.top + slot
            if index >= self.count:
                break
            row = Rect(rect.x, rect.y + slot * self.row_height, rect.w,
                       self.row_height)
            selected = index == self.selected
            hovered = index == self.hovered and not selected
            if selected:
                painter.highlight(row, "selection" if focused else "hover")
            elif hovered:
                painter.highlight(row, "hover")
            draw(painter, index, row, selected, hovered)
        self._scrollbar(painter, rect)

    def _scrollbar(self, painter: Painter, rect: Rect) -> None:
        if self.count <= self.visible or rect.h < 3:
            return
        span = rect.h
        thumb = max(1, round(span * self.visible / self.count))
        offset = round((span - thumb) * self.top / max(1, self.count - self.visible))
        x = rect.right - 1
        if painter.pixels:
            px = x * painter.cw + painter.cw - 4
            painter.canvas.fill_round_rect(
                px, (rect.y + offset) * painter.ch + 2, 3,
                thumb * painter.ch - 4, 1.5, painter.theme["ink_faint"])
        else:
            for row in range(span):
                glyph = "┃" if offset <= row < offset + thumb else "│"
                painter.text(x, rect.y + row, glyph,
                             "ink_muted" if glyph == "┃" else "panel_edge",
                             ellipsis=False)


# ---------------------------------------------------------------- line edit


class LineEdit:
    """A one-line text field with a real terminal cursor."""

    def __init__(self, text: str = "", placeholder: str = "",
                 max_length: int = 2000) -> None:
        self.text = text
        self.cursor = len(text)
        self.placeholder = placeholder
        self.max_length = max_length
        self.scroll = 0
        self.rect = Rect(0, 0, 0, 0)

    def set(self, text: str) -> None:
        self.text = text[: self.max_length]
        self.cursor = len(self.text)
        self.scroll = 0

    def _insert(self, text: str) -> None:
        text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
        text = "".join(c for c in text if c == " " or c.isprintable())
        room = self.max_length - len(self.text)
        text = text[: max(0, room)]
        self.text = self.text[: self.cursor] + text + self.text[self.cursor:]
        self.cursor += len(text)

    def _word_left(self) -> int:
        i = self.cursor
        while i > 0 and self.text[i - 1] == " ":
            i -= 1
        while i > 0 and self.text[i - 1] != " ":
            i -= 1
        return i

    def _word_right(self) -> int:
        i, n = self.cursor, len(self.text)
        while i < n and self.text[i] == " ":
            i += 1
        while i < n and self.text[i] != " ":
            i += 1
        return i

    def handle(self, event: Any) -> str | None:
        """'submit', 'cancel', 'changed', 'moved' or None (not consumed)."""
        from .runtime import Paste  # noqa: PLC0415 - avoid an import cycle

        if isinstance(event, Paste):
            self._insert(event.text)
            return "changed"
        text = typed_text(event)
        if text:
            self._insert(text)
            return "changed"
        key = chord(event)
        if key is None:
            m = mouse(event)
            if m is not None and is_click(event) and self.rect.contains(m.x, m.y):
                self.cursor = self._index_at(m.x - self.rect.x)
                return "moved"
            return None
        before = (self.text, self.cursor)
        if key == "enter":
            return "submit"
        if key == "escape":
            return "cancel"
        if key in ("backspace", "ctrl+h") and self.cursor:
            self.text = self.text[: self.cursor - 1] + self.text[self.cursor:]
            self.cursor -= 1
        elif key in ("delete", "ctrl+d") and self.cursor < len(self.text):
            self.text = self.text[: self.cursor] + self.text[self.cursor + 1:]
        elif key in ("left", "ctrl+b"):
            self.cursor = max(0, self.cursor - 1)
        elif key in ("right", "ctrl+f"):
            self.cursor = min(len(self.text), self.cursor + 1)
        elif key in ("home", "ctrl+a"):
            self.cursor = 0
        elif key in ("end", "ctrl+e"):
            self.cursor = len(self.text)
        elif key in ("ctrl+left", "alt+b"):
            self.cursor = self._word_left()
        elif key in ("ctrl+right", "alt+f"):
            self.cursor = self._word_right()
        elif key == "ctrl+u":
            self.text = self.text[self.cursor:]
            self.cursor = 0
        elif key == "ctrl+k":
            self.text = self.text[: self.cursor]
        elif key in ("ctrl+w", "ctrl+backspace", "alt+backspace"):
            start = self._word_left()
            self.text = self.text[:start] + self.text[self.cursor:]
            self.cursor = start
        elif key in ("backspace", "delete"):
            return "moved"  # at an edge: consumed, nothing to do
        else:
            return None
        if (self.text, self.cursor) == before:
            return "moved"
        return "changed" if self.text != before[0] else "moved"

    def _index_at(self, column: int) -> int:
        used = 0
        for index in range(self.scroll, len(self.text)):
            w = char_width(self.text[index])
            if used + w > column:
                return index
            used += w
        return len(self.text)

    def render(self, painter: Painter, rect: Rect, *, focused: bool,
               role: str = "field") -> None:
        self.rect = rect
        painter.highlight(rect, role) if painter.pixels else painter.fill(rect, role)
        if focused:
            painter.ring(rect, "accent")
        inner = Rect(rect.x + 1, rect.y + rect.h // 2, max(1, rect.w - 2), 1)
        if not self.text and not focused:
            painter.text(inner.x, inner.y, self.placeholder, "ink_faint",
                         limit=inner.right)
            return
        if not self.text and self.placeholder and focused:
            painter.text(inner.x, inner.y, self.placeholder, "ink_faint",
                         limit=inner.right)
        # Keep the cursor inside the visible window.
        self.scroll = min(self.scroll, self.cursor)
        while text_width(self.text[self.scroll:self.cursor]) > inner.w - 1:
            self.scroll += 1
        visible = self.text[self.scroll:]
        if self.text:
            painter.text(inner.x, inner.y, visible, "ink", limit=inner.right,
                         ellipsis=False)
        if focused:
            caret = inner.x + text_width(self.text[self.scroll:self.cursor])
            painter.show_cursor(min(caret, inner.right - 1), inner.y)


# ------------------------------------------------------------------ buttons


@dataclass
class Button:
    label: str
    action: str
    key: str = ""        # shown as a hint, e.g. "n"
    primary: bool = False
    danger: bool = False
    rect: Rect = field(default=Rect(0, 0, 0, 0))

    @property
    def width(self) -> int:
        hint = f" {self.key}" if self.key else ""
        return text_width(self.label) + text_width(hint) + 4


class ButtonRow:
    """A row of buttons. `handle` returns the clicked button's action."""

    def __init__(self, buttons: Sequence[Button]) -> None:
        self.buttons = list(buttons)
        self.hovered: str | None = None

    def handle(self, event: Any) -> str | None:
        m = mouse(event)
        if m is None:
            return None
        ki = _ki()
        if m.action == ki.MOUSE_MOVE:
            self.hovered = next((b.action for b in self.buttons
                                 if b.rect.contains(m.x, m.y)), None)
            return None
        if is_click(event):
            for button in self.buttons:
                if button.rect.contains(m.x, m.y):
                    return button.action
        return None

    def render(self, painter: Painter, x: int, y: int,
               limit: int | None = None, align_right: bool = False) -> int:
        """Draw from (x, y). Returns the columns used."""
        right = painter.width if limit is None else limit
        total = sum(b.width + 1 for b in self.buttons) - 1
        if align_right:
            x = max(x, right - total)
        start = x
        for button in self.buttons:
            if x + button.width > right:
                button.rect = Rect(0, 0, 0, 0)
                continue
            button.rect = Rect(x, y, button.width, 1)
            role = ("danger" if button.danger else "accent") if button.primary \
                else ("hover" if self.hovered == button.action else "panel")
            ink = "ink_invert" if button.primary else (
                "danger" if button.danger else "ink")
            if painter.pixels:
                px, py, pw, ph = painter._px(button.rect)
                painter.canvas.fill_round_rect(px + 1, py + 1, pw - 2, ph - 2,
                                               (ph - 2) / 2, painter.theme[role])
                if not button.primary:
                    painter.canvas.stroke_round_rect(
                        px + 1, py + 1, pw - 2, ph - 2, (ph - 2) / 2, 1.0,
                        painter.theme["panel_edge"])
                painter.grid.clear(button.rect)
            else:
                painter.fill(button.rect, role)
            used = painter.text(x + 2, y, button.label, ink,
                                bold=button.primary, limit=x + button.width)
            if button.key:
                painter.text(x + 2 + used + 1, y, button.key,
                             "ink_invert" if button.primary else "ink_faint",
                             limit=x + button.width)
            x += button.width + 1
        return x - start


# ------------------------------------------------------------------ dialogs


def centred(area: Rect, width: int, height: int) -> Rect:
    w = min(width, area.w - 2)
    h = min(height, area.h - 2)
    return Rect(area.x + (area.w - w) // 2, area.y + (area.h - h) // 2,
                max(1, w), max(1, h))


class ConfirmDialog:
    """A yes/no question. y/enter confirm, n/escape decline."""

    def __init__(self, title: str, message: str, confirm: str = "OK",
                 cancel: str = "Cancel", danger: bool = False) -> None:
        self.title = title
        self.message = message
        self.buttons = ButtonRow([
            Button(cancel, "cancel", "esc"),
            Button(confirm, "confirm", "enter", primary=True, danger=danger),
        ])

    def handle(self, event: Any) -> str | None:
        key = chord(event)
        if key in ("y", "enter"):
            return "confirm"
        if key in ("n", "escape", "q"):
            return "cancel"
        return self.buttons.handle(event)

    def render(self, painter: Painter, area: Rect) -> None:
        lines = _wrap(self.message, 56)
        box = centred(area, 64, len(lines) + 6)
        painter.panel(box, "panel")
        painter.text(box.x + 2, box.y + 1, self.title, "ink", bold=True,
                     limit=box.right - 2)
        for i, line in enumerate(lines):
            painter.text(box.x + 2, box.y + 3 + i, line, "ink_muted",
                         limit=box.right - 2)
        self.buttons.render(painter, box.x + 2, box.bottom - 2,
                            limit=box.right - 2, align_right=True)


@dataclass
class Field:
    key: str
    label: str
    value: str = ""
    kind: str = "text"            # "text" or "choice"
    choices: Sequence[str] = ()
    hint: str = ""
    placeholder: str = ""


class FormDialog:
    """Labelled fields in a modal panel.

    Tab and the arrow keys move between fields; a choice field cycles with
    space, left and right or a click. Enter on the last field, ctrl+s
    anywhere, or the Save button submits; escape cancels. `validate` may
    return an error message, which keeps the dialog open and shows it.
    """

    def __init__(self, title: str, fields: Sequence[Field], *,
                 submit: str = "Save",
                 validate: Callable[[dict[str, str]], str | None] | None = None,
                 width: int = 72) -> None:
        self.title = title
        self.fields = list(fields)
        self.edits = {f.key: LineEdit(f.value, f.placeholder)
                      for f in self.fields if f.kind == "text"}
        self.choice = {f.key: (list(f.choices).index(f.value)
                               if f.value in f.choices else 0)
                       for f in self.fields if f.kind == "choice"}
        self.focus = 0
        self.error = ""
        self.validate = validate
        self.width = width
        self.rows: dict[str, Rect] = {}
        self.buttons = ButtonRow([
            Button("Cancel", "cancel", "esc"),
            Button(submit, "submit", "ctrl+s", primary=True),
        ])

    def values(self) -> dict[str, str]:
        out = {}
        for f in self.fields:
            if f.kind == "choice":
                out[f.key] = list(f.choices)[self.choice[f.key]] if f.choices else ""
            else:
                out[f.key] = self.edits[f.key].text.strip()
        return out

    def _submit(self) -> str | None:
        if self.validate is not None:
            message = self.validate(self.values())
            if message:
                self.error = message
                return None
        return "submit"

    def _cycle(self, f: Field, step: int) -> None:
        if f.choices:
            self.choice[f.key] = (self.choice[f.key] + step) % len(f.choices)

    def handle(self, event: Any) -> str | None:
        key = chord(event)
        current = self.fields[self.focus]
        if key in ("tab", "down"):
            self.focus = (self.focus + 1) % len(self.fields)
            return None
        if key in ("shift+tab", "up"):
            self.focus = (self.focus - 1) % len(self.fields)
            return None
        if key == "ctrl+s":
            return self._submit()
        if key == "escape":
            return "cancel"
        clicked = self.buttons.handle(event)
        if clicked == "submit":
            return self._submit()
        if clicked == "cancel":
            return "cancel"
        m = mouse(event)
        if m is not None and is_click(event):
            for index, f in enumerate(self.fields):
                if self.rows.get(f.key, Rect(0, 0, 0, 0)).contains(m.x, m.y):
                    self.focus = index
                    if f.kind == "choice":
                        self._cycle(f, 1)
                    else:
                        self.edits[f.key].handle(event)
                    return None
            return None
        if current.kind == "choice":
            if key in ("space", "right", "l"):
                self._cycle(current, 1)
            elif key in ("left", "h"):
                self._cycle(current, -1)
            elif key == "enter":
                return self._advance()
            return None
        result = self.edits[current.key].handle(event)
        if result == "submit":
            return self._advance()
        if result == "cancel":
            return "cancel"
        if result == "changed":
            self.error = ""
        return None

    def _advance(self) -> str | None:
        if self.focus == len(self.fields) - 1:
            return self._submit()
        self.focus += 1
        return None

    def render(self, painter: Painter, area: Rect) -> None:
        height = 4 + 3 * len(self.fields) + (2 if self.error else 0) + 1
        box = centred(area, self.width, height)
        painter.panel(box, "panel")
        painter.text(box.x + 2, box.y + 1, self.title, "ink", bold=True,
                     limit=box.right - 2)
        label_w = min(14, max(text_width(f.label) for f in self.fields) + 2)
        y = box.y + 3
        for index, f in enumerate(self.fields):
            if y + 1 >= box.bottom - 2:
                break
            focused = index == self.focus
            painter.text(box.x + 2, y, f.label,
                         "ink" if focused else "ink_muted", bold=focused,
                         limit=box.x + 2 + label_w)
            field_rect = Rect(box.x + 2 + label_w, y, box.w - 4 - label_w, 1)
            self.rows[f.key] = field_rect
            if f.kind == "choice":
                painter.highlight(field_rect, "field")
                if focused:
                    painter.ring(field_rect)
                value = list(f.choices)[self.choice[f.key]] if f.choices else ""
                painter.text(field_rect.x + 1, y, "‹ " + value + " ›",
                             "accent" if focused else "ink",
                             limit=field_rect.right - 1)
            else:
                self.edits[f.key].render(painter, field_rect, focused=focused)
            if f.hint:
                painter.text(field_rect.x + 1, y + 1, f.hint, "ink_faint",
                             limit=field_rect.right)
            y += 3 if f.hint else 2
        if self.error:
            painter.text(box.x + 2, box.bottom - 4, self.error, "danger",
                         limit=box.right - 2)
        self.buttons.render(painter, box.x + 2, box.bottom - 2,
                            limit=box.right - 2, align_right=True)


class HelpOverlay:
    """A two-column table of keys and what they do."""

    def __init__(self, title: str, rows: Sequence[tuple[str, str]]) -> None:
        self.title = title
        self.rows = list(rows)

    def handle(self, event: Any) -> str | None:
        if chord(event) is not None or is_click(event):
            return "close"
        return None

    def render(self, painter: Painter, area: Rect) -> None:
        key_w = max((text_width(k) for k, _ in self.rows), default=4) + 3
        text_w = max((text_width(t) for _, t in self.rows), default=10)
        box = centred(area, key_w + text_w + 6, len(self.rows) + 5)
        painter.panel(box, "panel")
        painter.text(box.x + 2, box.y + 1, self.title, "ink", bold=True,
                     limit=box.right - 2)
        for i, (keys, text) in enumerate(self.rows):
            y = box.y + 3 + i
            if y >= box.bottom - 1:
                break
            painter.text(box.x + 2, y, keys, "accent", limit=box.x + 2 + key_w)
            painter.text(box.x + 2 + key_w, y, text, "ink_muted",
                         limit=box.right - 2)


def _wrap(text: str, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split(" "):
            candidate = f"{line} {word}" if line else word
            if text_width(candidate) <= width:
                line = candidate
            else:
                if line:
                    lines.append(line)
                line = clip(word, width)
        lines.append(line)
    return lines


wrap = _wrap
