"""Onde estão as bibliotecas: validar uma pasta, achar as conhecidas e onde criar uma nova."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .manager import (CONFIG_DIR_ENV, CONFIG_DIR_NAME, CURRENT_LIBRARY_FILE,
                      CURRENT_LIBRARY_KEY, DATABASE_FILE, DEFAULT_LIBRARY_NAME,
                      RECENT_LIBRARIES_FILE, RECENT_LIBRARIES_KEY)


def is_library(path: Path | str) -> bool:
    """Uma biblioteca sempre tem o banco de dados na raiz."""
    return bool(path) and (Path(path) / DATABASE_FILE).is_file()


def find_library_root(path: Path | str) -> Path | None:
    """A biblioteca que contém `path` (ele mesmo ou uma pasta acima), se houver."""
    current = Path(path).expanduser().absolute()
    return next((folder for folder in (current, *current.parents) if is_library(folder)), None)


def find_library_in(folder: Path | str) -> Path | None:
    """A própria pasta, se for biblioteca, ou a única biblioteca logo dentro dela
    (quem escolhe a pasta de cima em vez da pasta da biblioteca)."""
    folder = Path(folder)
    if is_library(folder):
        return folder
    try:
        children = [child for child in folder.iterdir() if child.is_dir() and is_library(child)]
    except OSError:
        return None
    return children[0] if len(children) == 1 else None


def new_library_path(parent: Path | str) -> Path:
    """Onde criar a biblioteca: a própria pasta, se estiver vazia, ou uma subpasta
    com o nome padrão (uma biblioteca nova precisa de uma pasta vazia)."""
    parent = Path(parent)
    if not parent.exists() or (parent.is_dir() and not any(parent.iterdir())):
        return parent
    candidate, number = parent / DEFAULT_LIBRARY_NAME, 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = parent / f"{DEFAULT_LIBRARY_NAME} {number}"
        number += 1
    return candidate


def manager_config_dir() -> Path:
    """Pasta de configuração do programa dono da biblioteca (mesma regra que ele usa)."""
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
    """Bibliotecas que este computador já usa (a atual primeiro, depois as mais usadas
    e a pasta padrão). Só devolve as que existem de verdade."""
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
