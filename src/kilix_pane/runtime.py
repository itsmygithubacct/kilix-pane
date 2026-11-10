"""Owning the terminal: modes, input, resize, redraw, and a clean exit.

An application implements three methods and never touches the terminal:

    class App:
        def render(self, painter): ...          # draw the whole frame
        def handle(self, event, ctx): ...       # keys, mouse, paste, resize
        def tick(self, now, ctx): ...           # optional; seconds to next

`run(app)` picks a backend, enters raw mode and the alternate screen, turns
on SGR mouse reporting, bracketed paste, focus events and the Kitty keyboard
protocol, and restores every one of them on every exit path, including an
exception and SIGTERM. `ctx.run_external()` lends the real terminal to a
child such as ``$EDITOR`` and repaints when it returns.

`render_text()` and `snapshot_png()` drive the same `render` headlessly, so
an application's tests and screenshots exercise its real drawing code.
"""

from __future__ import annotations

import errno
import fcntl
import os
import select
import signal
import struct
import subprocess
import sys
import termios
import time
import tty
import zlib
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from . import deps
from .cells import control_free
from .painter import Painter
from .screen import CellScreen, PixelScreen
from .theme import Theme, load_theme

__all__ = [
    "App",
    "Context",
    "Paste",
    "Resize",
    "choose_mode",
    "render_text",
    "run",
    "snapshot_png",
]

ESCAPE_TIMEOUT = 0.03


@dataclass(frozen=True)
class Resize:
    columns: int
    rows: int
    kind = "resize"


@dataclass(frozen=True)
class Paste:
    """A complete bracketed paste, reassembled from its chunks."""

    text: str
    kind = "paste"


class App(Protocol):
    def render(self, painter: Painter) -> None: ...
    def handle(self, event: Any, ctx: "Context") -> None: ...


def _kitty_input() -> Any:
    found = deps.find("kitty_input")
    if not found.ok:
        raise RuntimeError(
            "kilix-pane needs the kitty_input package (kitty-input/python). "
            f"{found.error}")
    return found.module


def graphics_likely(env: dict[str, str] | None = None) -> bool:
    """Whether the terminal speaks the Kitty graphics protocol.

    A heuristic on the environment, the same one the Kilix desktop uses:
    asking the terminal would mean reading a reply before the event loop owns
    input, and every terminal this stack ships is identified here.
    """
    env = os.environ if env is None else env
    if env.get("TMUX") or env.get("STY"):
        return False  # passthrough exists but placement geometry does not
    if env.get("KITTY_WINDOW_ID") or env.get("KILIX_STREAM") == "1":
        return True
    term = env.get("TERM", "")
    if "kitty" in term:
        return True
    return env.get("TERM_PROGRAM", "") in ("WezTerm", "ghostty")


def cell_pixels(fd: int) -> tuple[int, int, int, int]:
    """(columns, rows, cell width px, cell height px); pixels 0 if unknown."""
    try:
        packed = fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8)
        rows, columns, width, height = struct.unpack("HHHH", packed)
    except OSError:
        size = os.get_terminal_size(fd)
        return size.columns, size.lines, 0, 0
    if not (rows and columns):
        size = os.get_terminal_size(fd)
        return size.columns, size.lines, 0, 0
    cw = width // columns if width else 0
    ch = height // rows if height else 0
    return columns, rows, cw, ch


def choose_mode(requested: str = "auto", fd: int | None = None) -> tuple[str, str]:
    """('pixels' | 'cells', why). `requested` is auto, pixels or cells."""
    requested = (os.environ.get("KILIX_PANE_MODE") or requested).lower()
    if requested == "cells":
        return "cells", "requested"
    reasons = []
    if not graphics_likely():
        reasons.append("the terminal does not advertise the Kitty graphics protocol")
    library, why = deps.soft_raster_library()
    if library is None:
        reasons.append(f"soft-raster is unavailable ({why})")
    if fd is not None:
        try:
            _, _, cw, ch = cell_pixels(fd)
        except OSError:
            cw = ch = 0
        if not (cw and ch):
            reasons.append("the terminal does not report its cell size in pixels")
    if not reasons:
        return "pixels", "Kitty graphics, soft-raster and cell metrics available"
    if requested == "pixels":
        raise RuntimeError("pixels mode unavailable: " + "; ".join(reasons))
    return "cells", "; ".join(reasons)


class Context:
    """What an application may ask of the runtime."""

    def __init__(self, runtime: "_Runtime | None" = None) -> None:
        self._runtime = runtime
        self.quitting = False
        self.dirty = True

    @property
    def mode(self) -> str:
        return self._runtime.mode if self._runtime else "cells"

    @property
    def size(self) -> tuple[int, int]:
        return self._runtime.size if self._runtime else (80, 24)

    def quit(self) -> None:
        self.quitting = True

    def redraw(self) -> None:
        self.dirty = True

    def run_external(self, argv: Sequence[str], **kwargs: Any) -> int:
        """Run a full-screen child (an editor, a pager) on the real terminal."""
        if self._runtime is None:
            return subprocess.call(list(argv), **kwargs)
        return self._runtime.run_external(argv, **kwargs)

    def copy(self, text: str) -> None:
        """Put `text` on the clipboard through OSC 52 (Kilix and Kitty)."""
        if self._runtime is not None:
            import base64

            data = base64.b64encode(text.encode("utf-8")).decode("ascii")
            self._runtime.write(f"\x1b]52;c;{data}\x1b\\")


class _Runtime:
    def __init__(self, app: App, mode: str, theme: Theme, title: str | None,
                 max_fps: float) -> None:
        self.app = app
        self.mode = mode
        self.theme = theme
        self.title = title
        self.fd_in = sys.stdin.fileno()
        self.fd_out = sys.stdout.fileno()
        self.kitty_input = _kitty_input()
        self.decoder = self.kitty_input.Input()
        self.ctx = Context(self)
        self.size = (80, 24)
        self.cell = (8, 16)
        self.canvas: Any = None
        self.soft_raster: Any = None
        self.paste: list[bytes] = []
        self.max_fps = max_fps
        if mode == "pixels":
            self.soft_raster = deps.find("soft_raster").module
            presenter = deps.find("kitty_frame_presenter")
            self.screen: CellScreen = PixelScreen(
                self.write, presenter.module if presenter.ok else None,
                max_fps=max_fps)
        else:
            self.screen = CellScreen(self.write)
        self.wake_r, self.wake_w = os.pipe()
        for fd in (self.wake_r, self.wake_w):
            os.set_blocking(fd, False)
        self.pending_signals: list[int] = []

    # ---------------------------------------------------------------- io

    def write(self, data: str) -> None:
        payload = data.encode("utf-8", "replace")
        view = memoryview(payload)
        while view:
            try:
                written = os.write(self.fd_out, view)
            except InterruptedError:
                continue
            except BlockingIOError:
                select.select([], [self.fd_out], [], 1.0)
                continue
            view = view[written:]

    def enter(self) -> None:
        ki = self.kitty_input
        self.saved = termios.tcgetattr(self.fd_in)
        tty.setraw(self.fd_in)
        parts = ["\x1b[?1049h\x1b[?25l\x1b[?7l\x1b[2J",
                 ki.MOUSE_ON, ki.PASTE_ON, ki.FOCUS_ON,
                 ki.KEYBOARD_PUSH_DISAMBIGUATE]
        if self.title:
            parts.append(f"\x1b]2;{control_free(self.title)}\x1b\\")
        self.write("".join(parts))
        self.resize()

    def leave(self) -> None:
        ki = self.kitty_input
        out = [ki.KEYBOARD_POP, ki.FOCUS_OFF, ki.PASTE_OFF, ki.MOUSE_OFF]
        if isinstance(self.screen, PixelScreen):
            out.append(self.screen.close())
        out.append("\x1b[0m\x1b[?7h\x1b[0 q\x1b[?25h\x1b[?1049l")
        self.write("".join(out))
        termios.tcsetattr(self.fd_in, termios.TCSADRAIN, self.saved)

    def resize(self) -> None:
        columns, rows, cw, ch = cell_pixels(self.fd_out)
        self.size = (max(1, columns), max(1, rows))
        if cw and ch:
            self.cell = (cw, ch)
        if self.canvas is not None:
            self.canvas.close()
            self.canvas = None
        if self.mode == "pixels":
            if not (cw and ch):
                # A terminal that stopped reporting pixels: degrade rather
                # than draw at a guessed scale.
                self.mode = "cells"
                self.screen = CellScreen(self.write)
            else:
                self.canvas = self.soft_raster.Canvas(
                    self.size[0] * cw, self.size[1] * ch)
        self.screen.invalidate()
        self.ctx.dirty = True

    def draw(self) -> None:
        columns, rows = self.size
        if self.canvas is not None:
            self.canvas.clear(self.theme["surface"])
        painter = Painter(columns, rows, self.theme, canvas=self.canvas,
                          cell_size=self.cell)
        if self.canvas is None:
            painter.fill(painter.bounds, "surface")
        self.app.render(painter)
        if self.canvas is not None and isinstance(self.screen, PixelScreen):
            self.screen.present_frame(
                bytes(self.canvas.rgb_bytes()), self.canvas.width,
                self.canvas.height, columns, rows, painter.grid)
        else:
            self.screen.present(painter.grid)
        self.ctx.dirty = False

    def run_external(self, argv: Sequence[str], **kwargs: Any) -> int:
        self.leave()
        try:
            return subprocess.call(list(argv), **kwargs)
        finally:
            self.decoder.reset()
            self.enter()

    # -------------------------------------------------------------- loop

    def _on_signal(self, number: int, _frame: Any) -> None:
        self.pending_signals.append(number)
        try:
            os.write(self.wake_w, b"!")
        except OSError:
            pass

    def deliver(self, event: Any) -> None:
        ki = self.kitty_input
        if isinstance(event, ki.PasteEvent):
            self.paste.append(event.data)
            if not event.final:
                return
            text = b"".join(self.paste).decode("utf-8", "replace")
            self.paste.clear()
            event = Paste(text)
        self.app.handle(event, self.ctx)
        self.ctx.dirty = True

    def loop(self) -> None:
        escape_deadline: float | None = None
        tick = getattr(self.app, "tick", None)
        next_tick = time.monotonic() if tick else None
        while not self.ctx.quitting:
            if self.ctx.dirty:
                self.draw()
            now = time.monotonic()
            deadlines = [d for d in (escape_deadline, next_tick) if d is not None]
            timeout = max(0.0, min(deadlines) - now) if deadlines else None
            if isinstance(self.screen, PixelScreen) and self.screen.presenter:
                timeout = 0.05 if timeout is None else min(timeout, 0.05)
            try:
                ready, _, _ = select.select([self.fd_in, self.wake_r], [], [],
                                            timeout)
            except InterruptedError:
                ready = []
            if self.wake_r in ready:
                try:
                    os.read(self.wake_r, 64)
                except BlockingIOError:
                    pass
                while self.pending_signals:
                    number = self.pending_signals.pop(0)
                    if number == signal.SIGWINCH:
                        self.resize()
                        self.deliver(Resize(*self.size))
                    else:
                        self.ctx.quitting = True
            if self.fd_in in ready:
                try:
                    data = os.read(self.fd_in, 65536)
                except OSError as error:
                    if error.errno not in (errno.EAGAIN, errno.EINTR):
                        raise
                    continue
                if not data:
                    break  # the terminal went away
                self.decoder.feed(data)
                escape_deadline = (time.monotonic() + ESCAPE_TIMEOUT
                                   if self.decoder.has_pending_escape else None)
            elif escape_deadline is not None and time.monotonic() >= escape_deadline:
                self.decoder.flush_escape()
                escape_deadline = None
            for event in self.decoder:
                self.deliver(event)
                if self.ctx.quitting:
                    break
            if tick and next_tick is not None and time.monotonic() >= next_tick:
                wait = tick(time.monotonic(), self.ctx)
                next_tick = None if wait is None else time.monotonic() + max(0.05, wait)
            if isinstance(self.screen, PixelScreen):
                self.screen.flush()


def run(app: App, *, mode: str = "auto", theme: Theme | str | None = None,
        title: str | None = None, max_fps: float = 60) -> int:
    """Run `app` full-screen until it calls ``ctx.quit()``. Returns 0."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise RuntimeError("an interactive terminal is required")
    selected, _why = choose_mode(mode, sys.stdout.fileno())
    resolved = theme if isinstance(theme, Theme) else load_theme(theme)
    runtime = _Runtime(app, selected, resolved, title, max_fps)
    previous: dict[int, Any] = {}
    for number in (signal.SIGWINCH, signal.SIGTERM, signal.SIGHUP):
        previous[number] = signal.signal(number, runtime._on_signal)
    runtime.enter()
    try:
        runtime.loop()
    finally:
        try:
            runtime.leave()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
            os.close(runtime.wake_r)
            os.close(runtime.wake_w)
            if runtime.canvas is not None:
                runtime.canvas.close()
    return 0


# ----------------------------------------------------------------- headless


def render_text(app: App, columns: int = 100, rows: int = 30,
                theme: Theme | str | None = "dark") -> list[str]:
    """The app's frame in cells mode, as text lines (for tests and --dump)."""
    resolved = theme if isinstance(theme, Theme) else load_theme(theme)
    painter = Painter(columns, rows, resolved)
    painter.fill(painter.bounds, "surface")
    app.render(painter)
    return painter.grid.lines()


def render_painter(app: App, columns: int, rows: int, *, pixels: bool,
                   theme: Theme | str | None = "dark",
                   cell: tuple[int, int] = (9, 18)) -> Painter:
    resolved = theme if isinstance(theme, Theme) else load_theme(theme)
    canvas = None
    if pixels:
        library, why = deps.soft_raster_library()
        if library is None:
            raise RuntimeError(f"soft-raster unavailable: {why}")
        canvas = deps.find("soft_raster").module.Canvas(  # type: ignore[union-attr]
            columns * cell[0], rows * cell[1])
        canvas.clear(resolved["surface"])
    painter = Painter(columns, rows, resolved, canvas=canvas, cell_size=cell)
    if canvas is None:
        painter.fill(painter.bounds, "surface")
    app.render(painter)
    return painter


def snapshot_png(app: App, path: str, columns: int = 100, rows: int = 30, *,
                 pixels: bool = True, theme: Theme | str | None = "dark") -> str:
    """Write a PNG of one frame: the pixel layer plus the text grid.

    The text is drawn with soft-raster's embedded ASCII face, so this is a
    layout preview for documentation, not what the terminal shows; prove a
    real frame with a screenshot of a real pane.
    """
    cell = (9, 18)
    painter = render_painter(app, columns, rows, pixels=pixels, theme=theme,
                             cell=cell)
    sr = deps.find("soft_raster").module
    canvas = painter.canvas
    owned = canvas is None
    if canvas is None:
        if sr is None or deps.soft_raster_library()[0] is None:
            raise RuntimeError("snapshot_png needs soft-raster")
        canvas = sr.Canvas(columns * cell[0], rows * cell[1])
        canvas.clear(painter.theme["surface"])
    for y, row in enumerate(painter.grid.rows):
        for x, glyph in enumerate(row):
            if owned and glyph.style.bg is not None:
                canvas.fill_rect(x * cell[0], y * cell[1], cell[0], cell[1],
                                 glyph.style.bg)
            if glyph.char and glyph.char != " ":
                char = glyph.char if 32 <= ord(glyph.char) < 127 else _ascii_stand_in(glyph.char)
                fg = glyph.style.fg if glyph.style.fg is not None else painter.theme["ink"]
                canvas.text(x * cell[0], y * cell[1] + 1, char, fg)
    _write_png(path, bytes(canvas.rgb_bytes()), canvas.width, canvas.height)
    if owned:
        canvas.close()
    elif painter.canvas is not None:
        painter.canvas.close()
    return path


def _ascii_stand_in(char: str) -> str:
    return {"✓": "v", "…": ".", "─": "-", "│": "|", "┃": "|", "●": "o",
            "▌": "|", "█": "#", "·": ".", "‹": "<", "›": ">"}.get(char, "?")


def _write_png(path: str, rgb: bytes, width: int, height: int) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + kind + data
                + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF))

    stride = width * 3
    raw = b"".join(b"\x00" + rgb[y * stride:(y + 1) * stride]
                   for y in range(height))
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 6))
           + chunk(b"IEND", b""))
    with open(path, "wb") as handle:
        handle.write(png)
