"""Where the libraries are: validating a folder, finding the known ones and where to create a new one."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .manager import (CONFIG_DIR_ENV, CONFIG_DIR_NAME, CURRENT_LIBRARY_FILE,
                      CURRENT_LIBRARY_KEY, DATABASE_FILE, DEFAULT_LIBRARY_NAME,
                      RECENT_LIBRARIES_FILE, RECENT_LIBRARIES_KEY)


def is_library(path: Path | str) -> bool:
    """A library always has the database at its root."""
    return bool(path) and (Path(path) / DATABASE_FILE).is_file()


def find_library_root(path: Path | str) -> Path | None:
    """The library that contains `path` (itself or a folder above), if any."""
    current = Path(path).expanduser().absolute()
    return next((folder for folder in (current, *current.parents) if is_library(folder)), None)


def find_library_in(folder: Path | str) -> Path | None:
    """The folder itself, if it is a library, or the only library just inside it
    (for whoever picks the folder above instead of the library folder)."""
    folder = Path(folder)
    if is_library(folder):
        return folder
    try:
        children = [child for child in folder.iterdir() if child.is_dir() and is_library(child)]
    except OSError:
        return None
    return children[0] if len(children) == 1 else None


def new_library_path(parent: Path | str) -> Path:
    """Where to create the library: the folder itself, if it is empty, or a subfolder
    with the default name (a new library needs an empty folder)."""
    parent = Path(parent)
    if not parent.exists() or (parent.is_dir() and not any(parent.iterdir())):
        return parent
    candidate, number = parent / DEFAULT_LIBRARY_NAME, 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = parent / f"{DEFAULT_LIBRARY_NAME} {number}"
        number += 1
    return candidate


def manager_config_dir() -> Path:
    """Configuration folder of the program that owns the library (same rule it uses)."""
    custom = os.environ.get(CONFIG_DIR_ENV)
    if custom:
        return Path(custom)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / CONFIG_DIR_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / CONFIG_DIR_NAME
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / CONFIG_DIR_NAME


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def known_libraries(config_dir: Path | None = None) -> list[Path]:
    """Libraries this computer already uses (the current one first, then the most used
    and the default folder). Only returns the ones that really exist."""
    folder = config_dir or manager_config_dir()
    candidates: list[str] = []
    current = _read_json(folder / CURRENT_LIBRARY_FILE).get(CURRENT_LIBRARY_KEY)
    if isinstance(current, str):
        candidates.append(current)
    usage = _read_json(folder / RECENT_LIBRARIES_FILE).get(RECENT_LIBRARIES_KEY)
    if isinstance(usage, dict):
        def count(key: str) -> float:
            value = usage[key]
            return value if isinstance(value, (int, float)) else 0
        candidates += sorted((key for key in usage if isinstance(key, str)), key=count,
                             reverse=True)
    candidates.append(str(Path.home() / DEFAULT_LIBRARY_NAME))
    found: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        path = Path(raw).expanduser()
        key = os.path.normcase(str(path.absolute()))
        if key not in seen and is_library(path):
            seen.add(key)
            found.append(path)
    return found
