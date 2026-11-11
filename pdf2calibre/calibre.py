"""Integração opcional com o Calibre via `calibredb` (linha de comando)."""
from __future__ import annotations

import logging
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import BookEntry, Options
from .planner import sidecar_paths

logger = logging.getLogger(__name__)

_KNOWN_DIRS = (
    r"C:\Program Files\Calibre2",
    r"C:\Program Files (x86)\Calibre2",
    "/Applications/calibre.app/Contents/MacOS",
    "/usr/bin",
    "/opt/calibre",
)
_ADDED_IDS = re.compile(r"Added book ids?:\s*([\d,\s]+)", re.I)
ProgressFn = Callable[[int, int, str], None]


@dataclass
class ImportResult:
    """Resultado da importação de um livro."""

    entry: BookEntry
    ok: bool
    book_ids: list[int] = field(default_factory=list)
    message: str = ""
    duplicate: bool = False  # o Calibre já tinha um livro com mesmo título e autor


def find_calibredb(custom: str | None = None) -> Path | None:
    """Procura o executável `calibredb` (caminho informado, PATH e pastas comuns)."""
    candidates: list[Path] = []
    if custom:
        given = Path(custom)
        candidates += [given] if given.is_file() else [given / "calibredb.exe", given / "calibredb"]
    on_path = shutil.which("calibredb")
    if on_path:
        candidates.append(Path(on_path))
    for folder in _KNOWN_DIRS:
        candidates += [Path(folder) / "calibredb.exe", Path(folder) / "calibredb"]
    return next((item for item in candidates if item.is_file()), None)


def is_calibre_library(path: Path | str) -> bool:
    """Uma biblioteca do Calibre sempre tem o arquivo metadata.db na raiz."""
    return (Path(path) / "metadata.db").is_file()


DEFAULT_LIBRARY_NAME = "Calibre Library"  # nome que o próprio Calibre sugere


def calibre_config_dir() -> Path:
    """Pasta de configuração do Calibre (mesma regra de calibre/constants.py)."""
    custom = os.environ.get("CALIBRE_CONFIG_DIRECTORY")
    if custom:
        return Path(custom)
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or Path.home()) / "calibre"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Preferences" / "calibre"
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "calibre"


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def known_libraries(config_dir: Path | None = None) -> list[Path]:
    """Bibliotecas que o Calibre deste computador conhece (a atual primeiro).

    Lê global.py.json (library_path) e gui.json (library_usage_stats), e tenta a
    pasta padrão ~/Calibre Library. Só devolve as que existem de verdade.
    """
    folder = config_dir or calibre_config_dir()
    candidates: list[str] = []
    current = _read_json(folder / "global.py.json").get("library_path")
    if isinstance(current, str):
        candidates.append(current)
    stats = _read_json(folder / "gui.json").get("library_usage_stats")
    if isinstance(stats, dict):
        candidates += sorted((k for k in stats if isinstance(k, str)),
                             key=lambda k: stats[k] if isinstance(stats[k], (int, float)) else 0,
                             reverse=True)
    candidates.append(str(Path.home() / DEFAULT_LIBRARY_NAME))
    found: list[Path] = []
    seen: set[str] = set()
    for raw in candidates:
        path = Path(raw).expanduser()
        key = os.path.normcase(str(path.absolute()))
        if key not in seen and is_calibre_library(path):
            seen.add(key)
            found.append(path)
    return found


def find_library_in(folder: Path | str) -> Path | None:
    """A própria pasta, se for biblioteca, ou a única biblioteca logo dentro dela
    (quem escolhe 'Documentos' em vez de 'Documentos/Calibre Library')."""
    folder = Path(folder)
    if is_calibre_library(folder):
        return folder
    try:
        children = [child for child in folder.iterdir() if child.is_dir()
                    and is_calibre_library(child)]
    except OSError:
        return None
    return children[0] if len(children) == 1 else None


def new_library_path(parent: Path | str) -> Path:
    """Onde criar a biblioteca: a própria pasta, se estiver vazia, ou uma subpasta
    'Calibre Library' (o Calibre pede uma pasta vazia para uma biblioteca nova)."""
    parent = Path(parent)
    if not parent.exists() or (parent.is_dir() and not any(parent.iterdir())):
        return parent
    candidate, number = parent / DEFAULT_LIBRARY_NAME, 2
    while candidate.exists() and any(candidate.iterdir()):
        candidate = parent / f"{DEFAULT_LIBRARY_NAME} {number}"
        number += 1
    return candidate


def create_library(calibredb: Path, path: Path | str, timeout: int = 120) -> tuple[bool, str]:
    """Cria uma biblioteca vazia do Calibre em `path` (pasta vazia ou inexistente).

    Devolve (ok, mensagem de erro). Quem cria é o próprio Calibre (`calibredb`), então
    o banco sai no formato certo para a versão instalada.
    """
    path = Path(path)
    if is_calibre_library(path):
        return True, ""
    if path.exists() and (not path.is_dir() or any(path.iterdir())):
        return False, f"{path} não está vazia; o Calibre precisa de uma pasta vazia."
    created = not path.exists()
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"não foi possível criar a pasta: {exc}"
    try:
        done = _run([str(calibredb), "--with-library", str(path), "list"], timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        error = f"não foi possível executar o calibredb: {exc}"
    else:
        if done.returncode == 0 and is_calibre_library(path):
            return True, ""
        output = f"{done.stdout}\n{done.stderr}".strip()
        error = output.splitlines()[-1] if output else "erro desconhecido"
        if "running" in output.lower():
            error += " Feche o Calibre e tente de novo."
    if created:  # não deixa pasta criada por nós para trás
        shutil.rmtree(path, ignore_errors=True)
    return False, error


def find_library_root(path: Path | str) -> Path | None:
    """Devolve a biblioteca do Calibre que contém `path` (ele mesmo ou um pai), se houver."""
    current = Path(path).expanduser().absolute()
    for folder in (current, *current.parents):
        if is_calibre_library(folder):
            return folder
    return None


def build_add_command(calibredb: Path, library: Path, entry: BookEntry, options: Options,
                      cover: Path | None = None) -> list[str]:
    """Monta o comando `calibredb add` de um livro.

    Usa a forma `--opção=valor` para que um título começando com '-' não seja
    confundido com uma opção.
    """
    command = [str(calibredb), "add", "--with-library", str(library)]
    # O Calibre compara só título + autor: recusaria o volume 2 de "One Punch Man".
    # Para volumes o app compara título + autor + série + volume antes (library_import).
    is_volume = bool(entry.series) and entry.series_index is not None
    if not options.skip_duplicates or is_volume:
        command.append("--duplicates")
    command += [f"--title={entry.title}", f"--authors={entry.author}"]
    if entry.series:
        command.append(f"--series={entry.series}")
        command.append(f"--series-index={entry.series_index or 1:g}")
    if entry.language:
        command.append(f"--languages={entry.language}")
    tags = list(dict.fromkeys([*options.tags, *entry.tags]))
    if tags:
        command.append(f"--tags={','.join(tags)}")
    if cover is not None:
        command.append(f"--cover={cover}")
    command.append(str(entry.target_file or entry.source))
    return command


def parse_added_ids(output: str) -> list[int]:
    """Lê os ids que o calibredb informa em 'Added book ids: 12, 13'."""
    match = _ADDED_IDS.search(output)
    if not match:
        return []
    return [int(item) for item in re.findall(r"\d+", match.group(1))]


def _run(command: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    # O calibredb traduz as mensagens para o idioma do Calibre ("IDs de livro
    # adicionados: 12"); em inglês a leitura de "Added book ids" é confiável.
    # Saída em UTF-8 e decodificada com "replace": um título acentuado não pode
    # derrubar a importação com UnicodeDecodeError.
    env = {**os.environ, "CALIBRE_OVERRIDE_LANG": "en", "PYTHONIOENCODING": "utf-8"}
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout, check=False,
                          creationflags=flags, env=env)


def import_entries(entries: list[BookEntry], library: Path, options: Options,
                   calibredb: Path, progress: ProgressFn | None = None,
                   cancel: threading.Event | None = None,
                   timeout: int = 300) -> list[ImportResult]:
    """Adiciona cada livro à biblioteca com `calibredb add`.

    Título, autores, idioma, etiquetas e capa vão na linha de comando; o resto
    (ordenação, data de publicação) o calibredb lê do OPF com o mesmo nome do PDF.
    Feche o Calibre antes: com a janela aberta o calibredb recusa o acesso.
    """
    results: list[ImportResult] = []
    for index, entry in enumerate(entries, start=1):
        if cancel is not None and cancel.is_set():
            break
        cover = None
        if entry.target_file:
            _opf, candidate = sidecar_paths(entry.target_file, options.folder_per_book)
            cover = candidate if candidate.is_file() else None
        command = build_add_command(calibredb, library, entry, options, cover)
        try:
            done = _run(command, timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            results.append(ImportResult(entry, False, message=f"não foi possível executar: {exc}"))
        else:
            output = f"{done.stdout}\n{done.stderr}"
            ids = parse_added_ids(output)
            if done.returncode == 0 and ids:
                results.append(ImportResult(entry, True, ids))
            elif done.returncode == 0:
                results.append(ImportResult(entry, False, message="já existe na biblioteca",
                                            duplicate=True))
            else:
                hint = " Feche o Calibre e tente de novo." if "running" in output.lower() else ""
                tail = output.strip().splitlines()[-1] if output.strip() else "erro desconhecido"
                results.append(ImportResult(entry, False, message=f"{tail}{hint}"))
        if progress:
            progress(index, len(entries), entry.title)
    return results


def remove_books(calibredb: Path, library: Path, ids: list[int],
                 timeout: int = 300) -> tuple[bool, str]:
    """Remove livros com `calibredb remove` (vão para a lixeira do Calibre)."""
    if not ids:
        return True, ""
    command = [str(calibredb), "remove", "--with-library", str(library),
               ",".join(str(book_id) for book_id in ids)]
    try:
        done = _run(command, timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"não foi possível executar: {exc}"
    if done.returncode == 0:
        return True, ""
    output = f"{done.stdout}\n{done.stderr}".strip()
    tail = output.splitlines()[-1] if output else "erro desconhecido"
    hint = " Feche o Calibre e tente de novo." if "running" in output.lower() else ""
    return False, f"{tail}{hint}"
