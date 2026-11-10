from __future__ import annotations

import unittest

from kitty_input import decode

from kilix_pane import (ConfirmDialog, Field, FormDialog, LineEdit, ListView,
                        Paste, Rect, render_text)
from kilix_pane.painter import Painter
from kilix_pane.theme import DARK


def keys(wire: bytes) -> list:
    return decode(wire)


def feed(widget, wire: bytes) -> list:
    return [widget.handle(event) for event in keys(wire)]


class LineEditing(unittest.TestCase):
    def test_typing_and_cursor_keys(self) -> None:
        edit = LineEdit()
        feed(edit, "héllo 火".encode())
        self.assertEqual(edit.text, "héllo 火")
        feed(edit, b"\x1b[D\x7f")         # left, backspace: the space
        self.assertEqual(edit.text, "héllo火")
        feed(edit, b"\x1b[D\x1b[D\x7f")   # left left backspace: the l
        self.assertEqual(edit.text, "hélo火")
        feed(edit, b"\x01X\x05Y")         # ctrl+a X ctrl+e Y
        self.assertEqual(edit.text, "Xhélo火Y")

    def test_kill_and_word_commands(self) -> None:
        edit = LineEdit("buy milk and eggs")
        feed(edit, b"\x17")               # ctrl+w
        self.assertEqual(edit.text, "buy milk and ")
        feed(edit, b"\x01\x0b")           # ctrl+a ctrl+k
        self.assertEqual(edit.text, "")
        edit.set("one two")
        feed(edit, b"\x15")               # ctrl+u
        self.assertEqual(edit.text, "")

    def test_kitty_protocol_keys_work_too(self) -> None:
        edit = LineEdit("abc")
        feed(edit, b"\x1b[97;5u")         # ctrl+a, kitty encoding
        self.assertEqual(edit.cursor, 0)
        self.assertEqual(feed(edit, b"\x1b[13u"), ["submit"])
        self.assertEqual(feed(edit, b"\x1b[27u"), ["cancel"])

    def test_paste_is_one_line_and_bounded(self) -> None:
        edit = LineEdit(max_length=10)
        edit.handle(Paste("line one\nline two"))
        self.assertEqual(edit.text, "line one l")

    def test_control_chords_do_not_insert_text(self) -> None:
        edit = LineEdit()
        feed(edit, b"\x1b[115;5u")        # ctrl+s
        self.assertEqual(edit.text, "")

    def test_render_places_the_real_cursor(self) -> None:
        painter = Painter(20, 3, DARK)
        edit = LineEdit("abc")
        edit.render(painter, Rect(0, 1, 20, 1), focused=True)
        self.assertEqual(painter.cursor, (4, 1))
        self.assertIn("abc", painter.grid.lines()[1])

    def test_long_text_scrolls_to_keep_cursor_visible(self) -> None:
        painter = Painter(12, 1, DARK)
        edit = LineEdit("abcdefghijklmnopqrstuvwxyz")
        edit.render(painter, Rect(0, 0, 12, 1), focused=True)
        self.assertLessEqual(painter.cursor[0], 10)
        self.assertIn("z", painter.grid.lines()[0])


class Lists(unittest.TestCase):
    def make(self, count: int = 20) -> ListView:
        view = ListView(row_height=2)
        painter = Painter(40, 10, DARK)
        view.set_count(count)
        view.render(painter, Rect(0, 0, 40, 10), lambda *a: None)
        return view

    def test_keyboard_navigation_scrolls(self) -> None:
        view = self.make()
        self.assertEqual(view.visible, 5)
        feed(view, b"j" * 7)
        self.assertEqual(view.selected, 7)
        self.assertEqual(view.top, 3)
        feed(view, b"G")
        self.assertEqual(view.selected, 19)
        feed(view, b"g")
        self.assertEqual((view.selected, view.top), (0, 0))

    def test_click_selects_and_double_click_activates(self) -> None:
        view = self.make()
        results = feed(view, b"\x1b[<0;5;5M\x1b[<0;5;5m\x1b[<0;5;5M")
        self.assertEqual(view.selected, 2)
        self.assertEqual(results[0], "select")
        self.assertEqual(results[2], "activate")

    def test_wheel_scrolls_without_moving_selection(self) -> None:
        view = self.make()
        feed(view, b"\x1b[<65;5;5M")
        self.assertEqual((view.top, view.selected), (3, 0))

    def test_empty_list(self) -> None:
        view = self.make(0)
        self.assertEqual(feed(view, b"j\r"), [None, None])


class Dialogs(unittest.TestCase):
    def form(self) -> FormDialog:
        return FormDialog("New", [
            Field("title", "Title"),
            Field("prio", "Priority", "low", kind="choice",
                  choices=("none", "low", "high")),
        ], validate=lambda v: None if v["title"] else "title required")

    def test_form_validation_then_submit(self) -> None:
        form = self.form()
        self.assertIsNone(form.handle(keys(b"\x1b[115;5u")[0]))  # ctrl+s
        self.assertEqual(form.error, "title required")
        feed(form, b"Pay rent")
        self.assertEqual(form.error, "")
        feed(form, b"\t ")                 # next field, cycle choice
        self.assertEqual(form.values(), {"title": "Pay rent", "prio": "high"})
        self.assertEqual(feed(form, b"\r"), ["submit"])

    def test_form_escape_cancels(self) -> None:
        self.assertEqual(feed(self.form(), b"\x1b[27u"), ["cancel"])

    def test_form_renders_inside_area(self) -> None:
        painter = Painter(80, 24, DARK)
        form = self.form()
        form.render(painter, painter.bounds)
        text = "\n".join(painter.grid.lines())
        self.assertIn("New", text)
        self.assertIn("‹ low ›", text)
        self.assertIn("Save", text)

    def test_confirm(self) -> None:
        dialog = ConfirmDialog("Delete?", "Gone for good.")
        self.assertEqual(feed(dialog, b"y"), ["confirm"])
        self.assertEqual(feed(dialog, b"n"), ["cancel"])
        painter = Painter(80, 24, DARK)
        dialog.render(painter, painter.bounds)
        ok = next(b for b in dialog.buttons.buttons if b.action == "confirm")
        click = f"\x1b[<0;{ok.rect.x + 2};{ok.rect.y + 1}M".encode()
        self.assertEqual(feed(dialog, click), ["confirm"])


class Headless(unittest.TestCase):
    def test_demo_renders_in_both_widths(self) -> None:
        from kilix_pane.__main__ import Demo

        for columns, rows in ((100, 30), (40, 12), (12, 5)):
            lines = render_text(Demo(), columns, rows)
            self.assertEqual(len(lines), rows)
            self.assertTrue(all(len(line) <= columns for line in lines))


if __name__ == "__main__":
    unittest.main()
