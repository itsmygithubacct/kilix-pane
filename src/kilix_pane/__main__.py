"""`python3 -m kilix_pane doctor | demo [--cells|--pixels] | snapshot OUT.png`"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from . import deps
from .cells import Rect
from .painter import Painter
from .runtime import Context, choose_mode, run, snapshot_png
from .widgets import (Button, ButtonRow, ConfirmDialog, Field, FormDialog,
                      HelpOverlay, LineEdit, ListView, chord)


class Demo:
    """Every widget on one screen; what `make demo` shows."""

    def __init__(self) -> None:
        self.items = [("Water the plants", False, "p2"),
                      ("Book the dentist — ask about 火曜日", False, "p1"),
                      ("Back up the photo library", True, "p3"),
                      ("Renew the domain", False, None)] * 3
        self.list = ListView(row_height=2)
        self.edit = LineEdit(placeholder="Type here; enter adds an item")
        self.focus = "list"
        self.toolbar = ButtonRow([Button("Add", "add", "a", primary=True),
                                  Button("Form", "form", "f"),
                                  Button("Confirm", "confirm", "c"),
                                  Button("Help", "help", "?")])
        self.modal: Any = None
        self.message = ""

    def render(self, p: Painter) -> None:
        bounds = p.bounds
        side, main = bounds.take_left(min(26, bounds.w // 3))
        p.fill(side, "sidebar")
        p.text(2, 1, "kilix-pane", "ink", bold=True, limit=side.right - 1)
        p.text(2, 2, f"{'pixels' if p.pixels else 'cells'} backend",
               "ink_muted", limit=side.right - 1)
        for i, (role, label) in enumerate((("ok", "ok"), ("warn", "warn"),
                                           ("danger", "danger"),
                                           ("info", "info"))):
            p.dot(2, 4 + i, role)
            p.text(4, 4 + i, label, "ink_muted", limit=side.right - 1)
        p.text(2, 9, "progress", "ink_faint")
        p.bar(Rect(2, 10, side.w - 4, 1), 0.62)
        header, body = Rect(main.x + 1, main.y, main.w - 2, main.h).take_top(3)
        self.toolbar.render(p, header.x, 1, limit=header.right)
        field, body = body.take_top(3)
        self.edit.render(p, Rect(field.x, field.y, field.w, 1),
                         focused=self.focus == "edit")
        status, body = body.take_bottom(1)
        self.list.set_count(len(self.items))

        def draw(p: Painter, index: int, row: Rect, selected: bool,
                 hovered: bool) -> None:
            title, done, prio = self.items[index]
            if prio:
                p.stripe(row.x, row.y, row.h, prio)
            p.check(row.x + 2, row.y, done)
            p.text(row.x + 6, row.y, title, "ink_faint" if done else "ink",
                   strike=done, limit=row.right - 2)
            x = row.x + 6
            x += p.chip(x, row.y + 1, "#home", limit=row.right - 2) + 1
            p.text(x, row.y + 1, "due tomorrow", "ink_muted",
                   limit=row.right - 2)

        self.list.render(p, body, draw, focused=self.focus == "list")
        p.text(status.x, status.y, self.message or
               "tab focus · space toggle · a/f/c/? · q quit", "ink_faint",
               limit=status.right)
        if self.modal is not None:
            self.modal.render(p, bounds)

    def handle(self, event: Any, ctx: Context) -> None:
        if self.modal is not None:
            result = self.modal.handle(event)
            if result in ("submit", "confirm"):
                self.message = f"{type(self.modal).__name__}: {result}"
                if isinstance(self.modal, FormDialog):
                    self.message += f" {self.modal.values()}"
                self.modal = None
            elif result in ("cancel", "close"):
                self.modal = None
            return
        if self.focus == "edit":
            result = self.edit.handle(event)
            if result == "submit" and self.edit.text.strip():
                self.items.insert(0, (self.edit.text.strip(), False, None))
                self.edit.set("")
            elif result == "cancel" or chord(event) == "tab":
                self.focus = "list"
            if result is not None or chord(event) == "tab":
                return
        action = self.toolbar.handle(event)
        key = chord(event)
        if key == "q" or key == "ctrl+c":
            ctx.quit()
        elif key == "tab":
            self.focus = "edit"
        elif action == "add" or key == "a":
            self.focus = "edit"
        elif action == "form" or key == "f":
            self.modal = FormDialog("A form", [
                Field("title", "Title", "Something", placeholder="required"),
                Field("when", "When", "tomorrow", hint="today, fri, 2026-12-01"),
                Field("prio", "Priority", "medium", kind="choice",
                      choices=("none", "low", "medium", "high")),
            ], validate=lambda v: None if v["title"] else "A title is required")
        elif action == "confirm" or key == "c":
            self.modal = ConfirmDialog("Delete it?", "This removes the item "
                                       "for good.", "Delete", danger=True)
        elif action == "help" or key == "?":
            self.modal = HelpOverlay("Keys", [("j k ↑ ↓", "move"),
                                              ("space", "toggle"),
                                              ("tab", "focus the field"),
                                              ("q", "quit")])
        elif key == "space" and self.items:
            t, d, pr = self.items[self.list.selected]
            self.items[self.list.selected] = (t, not d, pr)
        else:
            self.list.handle(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python3 -m kilix_pane")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="report which backend this terminal gets")
    demo = sub.add_parser("demo", help="every widget on one screen")
    demo.add_argument("--cells", action="store_const", const="cells",
                      dest="mode", default="auto")
    demo.add_argument("--pixels", action="store_const", const="pixels",
                      dest="mode")
    shot = sub.add_parser("snapshot", help="write a PNG preview of the demo")
    shot.add_argument("output")
    shot.add_argument("--cells", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        for name, ok, where in deps.report():
            print(f"{'ok ' if ok else 'no '} {name:22} {where}")
        fd = sys.stdout.fileno() if sys.stdout.isatty() else None
        mode, why = choose_mode("auto", fd)
        print(f"backend: {mode} ({why})")
        return 0
    if args.command == "snapshot":
        snapshot_png(Demo(), args.output, 100, 30, pixels=not args.cells)
        print(args.output)
        return 0
    return run(Demo(), mode=args.mode, title="kilix-pane demo")


if __name__ == "__main__":
    raise SystemExit(main())
