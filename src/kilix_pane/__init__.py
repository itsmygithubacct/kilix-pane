"""kilix-pane: Kilix-native terminal interfaces in Python.

One widget tree, two backends. In a Kilix (or Kitty) pane the shapes are
drawn as pixels beneath the terminal's own text; anywhere else the same
widgets draw with characters and colours. See `runtime` for the application
contract and `painter` for the drawing API.
"""

from .cells import CellGrid, Rect, Style, char_width, clip, text_width
from .painter import Painter
from .runtime import (
    Context,
    Paste,
    Resize,
    choose_mode,
    render_text,
    run,
    snapshot_png,
)
from .theme import DARK, LIGHT, Theme, load_theme
from .widgets import (
    Button,
    ButtonRow,
    ConfirmDialog,
    Field,
    FormDialog,
    HelpOverlay,
    LineEdit,
    ListView,
    chord,
    is_click,
    mouse,
    wrap,
)

__version__ = "0.1.0"

__all__ = [
    "Button", "ButtonRow", "CellGrid", "ConfirmDialog", "Context", "DARK",
    "Field", "FormDialog", "HelpOverlay", "LIGHT", "LineEdit", "ListView",
    "Painter", "Paste", "Rect", "Resize", "Style", "Theme", "char_width",
    "chord", "choose_mode", "clip", "is_click", "load_theme", "mouse",
    "render_text", "run", "snapshot_png", "text_width", "wrap",
]
