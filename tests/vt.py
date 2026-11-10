"""A tiny VT replayer for tests: enough of the protocol to check our output.

It understands exactly what `screen.py` emits -- CUP, ED 2, SGR, DECSCUSR,
cursor show/hide, save/restore cursor, APC graphics -- and places characters
with the same width rules. Anything else fails the test, so the writer cannot
quietly start emitting sequences nobody checked.

Graphics are kept as the set of placed image ids, as a terminal would: `a=T`
and `a=p` place, `a=d` deletes, and ED 2 deletes every placement (kitty's
erase-in-display clears the graphics manager). An `a=f` frame edit sent to an
image with no placement is counted in `lost_edits`: nothing would show it. A
shared-memory transmission (`t=s`) is unlinked once read, as the terminal does,
so the presenter's slots come free.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.util
import re

from kilix_pane.cells import char_width

_CSI = re.compile(r"\x1b\[([0-9;?]*)([ -/]*)([@-~])")


class VT:
    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.cells = [[" "] * width for _ in range(height)]
        self.x = self.y = 0
        self.cursor_visible = True
        self.images = 0
        self.placements: set[str] = set()
        self.lost_edits = 0

    def feed(self, data: str) -> None:
        i = 0
        while i < len(data):
            if data.startswith("\x1b_G", i):
                end = data.index("\x1b\\", i)
                self.images += 1
                self._graphics(data[i + 3:end])
                i = end + 2
                continue
            if data.startswith("\x1b7", i) or data.startswith("\x1b8", i):
                i += 2
                continue
            match = _CSI.match(data, i)
            if match:
                self._csi(*match.groups())
                i = match.end()
                continue
            char = data[i]
            if char == "\x1b":
                raise AssertionError(f"unexpected escape at {data[i:i + 12]!r}")
            w = char_width(char)
            if w and 0 <= self.y < self.height and self.x + w <= self.width:
                self.cells[self.y][self.x] = char
                if w == 2:
                    self.cells[self.y][self.x + 1] = ""
            self.x += w
            i += 1

    def _csi(self, params: str, intermediate: str, final: str) -> None:
        if final == "H":
            parts = [int(p) if p else 1 for p in params.split(";")] if params else [1, 1]
            self.y, self.x = parts[0] - 1, parts[1] - 1
        elif final == "J" and params == "2":
            self.cells = [[" "] * self.width for _ in range(self.height)]
            self.placements.clear()
        elif final == "m":
            pass
        elif final == "q" and intermediate == " ":
            pass
        elif final in "hl" and params == "?25":
            self.cursor_visible = final == "h"
        elif final in "hl" and params == "?2026":
            pass  # synchronized update brackets around a presenter frame
        else:
            raise AssertionError(f"unexpected CSI {params!r}{intermediate!r}{final!r}")

    def _graphics(self, body: str) -> None:
        control, _, payload = body.partition(";")
        keys = dict(item.split("=", 1) for item in control.split(",") if "=" in item)
        action, image = keys.get("a", "t"), keys.get("i")
        if action in ("T", "p"):
            self.placements.add(image)
        elif action == "f" and image not in self.placements:
            self.lost_edits += 1
        elif action == "d":
            if keys.get("d", "a") in "aA":
                self.placements.clear()
            else:
                self.placements.discard(image)
        if keys.get("t") == "s" and payload:
            _shm_unlink(base64.b64decode(payload))

    def text(self) -> str:
        return "\n".join("".join(row) for row in self.cells)


def _shm_unlink(name: bytes) -> None:
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    libc.shm_unlink.argtypes = [ctypes.c_char_p]
    libc.shm_unlink(name)   # gone already is fine
