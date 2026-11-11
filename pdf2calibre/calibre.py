"""Integração opcional com o Calibre via `calibredb` (linha de comando)."""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .models import BookEntry, Options

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


def build_add_command(calibredb: Path, library: Path, entry: BookEntry, options: Options,
                      cover: Path | None = None) -> list[str]:
    """Monta o comando `calibredb add` de um livro.

    Usa a forma `--opção=valor` para que um título começando com '-' não seja
    confundido com uma opção.
    """
    command = [str(calibredb), "add", "--with-library", str(library)]
    if not options.skip_duplicates:
        command.append("--duplicates")
    command += [f"--title={entry.title}", f"--authors={entry.author}"]
    if entry.language:
        command.append(f"--languages={entry.language}")
    if options.tags:
        command.append(f"--tags={','.join(options.tags)}")
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
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                          check=False, creationflags=flags)


def import_entries(entries: list[BookEntry], library: Path, options: Options,
                   calibredb: Path, progress: ProgressFn | None = None,
                   cancel: threading.Event | None = None,
                   timeout: int = 300) -> list[ImportResult]:
    """Adiciona cada livro à biblioteca com `calibredb add`.

    Feche o Calibre antes: com a janela aberta o calibredb recusa o acesso.
    """
    results: list[ImportResult] = []
    for index, entry in enumerate(entries, start=1):
        if cancel is not None and cancel.is_set():
            break
        cover = None
        if entry.target_file:
            candidate = entry.target_file.parent / "cover.jpg"
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
                results.append(ImportResult(entry, False, message="já existe na biblioteca"))
            else:
                hint = " Feche o Calibre e tente de novo." if "running" in output.lower() else ""
                tail = output.strip().splitlines()[-1] if output.strip() else "erro desconhecido"
                results.append(ImportResult(entry, False, message=f"{tail}{hint}"))
        if progress:
            progress(index, len(entries), entry.title)
    return results
