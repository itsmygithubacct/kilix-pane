"""Named colour roles. Widgets ask for a role, never for a colour."""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path

__all__ = ["Theme", "DARK", "LIGHT", "load_theme"]


def _rgb(text: str) -> int:
    return int(text.lstrip("#"), 16)


@dataclass(frozen=True)
class Theme:
    name: str
    roles: dict[str, int] = field(default_factory=dict)

    def __getitem__(self, role: str) -> int:
        try:
            return self.roles[role]
        except KeyError:
            return self.roles["ink"]

    def with_roles(self, **roles: str | int) -> "Theme":
        merged = dict(self.roles)
        for key, value in roles.items():
            merged[key] = _rgb(value) if isinstance(value, str) else value
        return replace(self, roles=merged)


def _theme(name: str, **roles: str) -> Theme:
    return Theme(name, {k: _rgb(v) for k, v in roles.items()})


# Roles:
#   surface      the window background
#   sidebar      the navigation column
#   panel        a raised card or dialog
#   panel_edge   its outline
#   selection    the selected row
#   hover        the row under the pointer
#   field        an input field's well
#   ink          body text            ink_muted   secondary text
#   ink_faint    hints, disabled      ink_invert  text on accent
#   accent       primary actions, focus rings, checkmarks
#   ok warn danger info   status colours
#   p1 p2 p3     priority stripes (high, medium, low)
#   tag          tag chips
DARK = _theme(
    "dark",
    surface="#16181d", sidebar="#1c1f26", panel="#232731",
    panel_edge="#343a48", selection="#2d3a55", hover="#262c38",
    field="#11131a", ink="#e6e9ef", ink_muted="#a3abba", ink_faint="#6b7385",
    ink_invert="#0d1117", accent="#6ea8fe", ok="#5fd38d", warn="#f2c14e",
    danger="#f2706b", info="#7fc8f8", p1="#f2706b", p2="#f2c14e",
    p3="#6ea8fe", tag="#3b3f5c",
)
LIGHT = _theme(
    "light",
    surface="#f6f7f9", sidebar="#eceef2", panel="#ffffff",
    panel_edge="#d5d9e0", selection="#dbe7ff", hover="#e9edf5",
    field="#ffffff", ink="#1d2129", ink_muted="#566070", ink_faint="#8e97a6",
    ink_invert="#ffffff", accent="#2f6fdb", ok="#1e9e5a", warn="#b8860b",
    danger="#d23c36", info="#1f7fbf", p1="#d23c36", p2="#c98a00",
    p3="#2f6fdb", tag="#e3e7f3",
)
THEMES = {"dark": DARK, "light": LIGHT}


def _settings_theme(path: Path) -> str | None:
    """`theme=` from the shared Kilix settings file, if it says light/dark."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep and key.strip().lower() in ("theme", "kilix_theme", "color_scheme"):
            value = value.strip().strip("\"'").lower()
            if "light" in value:
                return "light"
            if "dark" in value:
                return "dark"
    return None


def load_theme(name: str | None = None) -> Theme:
    """`name`, else ``$KILIX_PANE_THEME``, else Kilix settings, else dark."""
    chosen = name or os.environ.get("KILIX_PANE_THEME")
    if not chosen:
        home = os.environ.get("GPU_TERMINAL_HOME") or str(
            Path.home() / ".local" / "gpu_terminal")
        chosen = _settings_theme(Path(home) / "settings.conf")
    return THEMES.get((chosen or "dark").lower(), DARK)
