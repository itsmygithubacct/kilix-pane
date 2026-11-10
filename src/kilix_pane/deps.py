"""Finding the optional stack modules, in one place.

Every graphical Python application on this stack has carried its own copy of
"try the import, then look in a few sibling checkouts". This is that search,
written once. The order is:

1. an ordinary import (a Debian package, a venv, PYTHONPATH);
2. ``third_party/<repo>`` beside the application (its pinned submodules);
3. sibling checkouts under ``$GPU_TERMINAL_HOME``, ``~/gpu_terminal`` and
   ``~/.local/gpu_terminal/sources``;
4. Kilix's own pinned copy under ``$KILIX_HOME/third_party``.

A module that is not found is reported, not raised: the pixel backend is
optional and everything degrades to the cell backend.
"""

from __future__ import annotations

import importlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

__all__ = ["Found", "add_roots", "find", "report", "soft_raster_library"]

#: module name -> (repository name, path of the package's parent inside it)
KNOWN = {
    "kitty_input": ("kitty-input", "python/src"),
    "soft_raster": ("soft-raster", "python/src"),
    "kitty_frame_presenter": ("kitty-frame-presenter", "src"),
    "kilix_pane": ("kilix-pane", "src"),
}

_extra_roots: list[Path] = []


def add_roots(*roots: str | os.PathLike[str]) -> None:
    """Search these directories first for ``<repo>/<subdir>`` (an app passes
    its own ``third_party``)."""
    for root in roots:
        path = Path(root)
        if path not in _extra_roots:
            _extra_roots.append(path)


def _search_roots() -> list[Path]:
    roots = list(_extra_roots)
    home = Path.home()
    gpu = os.environ.get("GPU_TERMINAL_HOME")
    for base in filter(None, (gpu, str(home / "gpu_terminal"),
                              str(home / ".local" / "gpu_terminal" / "sources"))):
        for group in ("kilix-modules", "kilix-apps", ""):
            roots.append(Path(base) / group if group else Path(base))
    kilix_home = os.environ.get("KILIX_HOME")
    if kilix_home:
        roots.append(Path(kilix_home) / "third_party")
    return roots


@dataclass
class Found:
    name: str
    module: ModuleType | None
    origin: str
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.module is not None


_cache: dict[str, Found] = {}


def find(name: str) -> Found:
    """Import `name` from wherever the stack keeps it."""
    if name in _cache:
        return _cache[name]
    try:
        module = importlib.import_module(name)
        found = Found(name, module, getattr(module, "__file__", "") or "import")
    except ImportError as error:
        found = Found(name, None, "", str(error))
        repo, subdir = KNOWN.get(name, (name.replace("_", "-"), "src"))
        for root in _search_roots():
            candidate = root / repo / subdir
            if not (candidate / name / "__init__.py").is_file():
                continue
            sys.path.insert(0, str(candidate))
            try:
                module = importlib.import_module(name)
            except ImportError as nested:
                sys.path.remove(str(candidate))
                found.error = str(nested)
                continue
            found = Found(name, module, str(candidate))
            break
    _cache[name] = found
    return found


def soft_raster_library() -> tuple[object | None, str]:
    """The loaded soft-raster native library, or None and why not.

    The binding finds ``libsoft-raster.so`` on its own when it sits in the
    usual places; a sibling checkout's ``build/`` is tried as well, because
    that is where an application's ``make all`` builds its pinned copy.
    """
    found = find("soft_raster")
    if not found.ok:
        return None, found.error or "soft_raster is not installed"
    module = found.module
    try:
        return module.default_library(), ""  # type: ignore[union-attr]
    except Exception as error:  # noqa: BLE001 - any failure means unusable
        first = str(error)
    if os.environ.get("SOFT_RASTER_LIBRARY"):
        return None, first
    package_root = Path(found.origin)
    candidates = [package_root.parent.parent / "build" / "libsoft-raster.so"]
    for root in _search_roots():
        candidates.append(root / "soft-raster" / "build" / "libsoft-raster.so")
    for candidate in candidates:
        if not candidate.is_file():
            continue
        # The binding's own override, set before its cached loader succeeds
        # once: every later `Canvas()` then uses this library.
        os.environ["SOFT_RASTER_LIBRARY"] = str(candidate)
        try:
            return module.default_library(), ""  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            del os.environ["SOFT_RASTER_LIBRARY"]
    return None, first


def report() -> list[tuple[str, bool, str]]:
    """(name, available, where-or-why) for every module this package uses."""
    rows = []
    for name in ("kitty_input", "kitty_frame_presenter", "soft_raster"):
        found = find(name)
        rows.append((name, found.ok, found.origin if found.ok else found.error))
    library, why = soft_raster_library()
    rows.append(("libsoft-raster", library is not None,
                 str(getattr(library, "path", "loaded")) if library else why))
    return rows
