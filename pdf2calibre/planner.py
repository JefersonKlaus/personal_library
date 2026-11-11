"""Planejamento: achar PDFs, analisar em paralelo, marcar duplicados e destinos."""
from __future__ import annotations

import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from .metadata import build_entry, sha256_file
from .models import USABLE_STATUSES, BookEntry, Options, Status
from .library import fold
from .naming import book_stem, natural_key, sanitize_component

ProgressFn = Callable[[int, int, str], None]


def find_pdfs(paths: Iterable[Path | str], recursive: bool = True,
              exclude: Path | None = None) -> list[Path]:
    """Lista os PDFs de arquivos e pastas dados, sem repetir nem entrar em `exclude`."""
    seen: set[Path] = set()
    found: list[Path] = []
    excluded = exclude.resolve() if exclude else None

    def add(candidate: Path) -> None:
        try:
            key = candidate.resolve()
        except OSError:
            return
        if key in seen:
            return
        if excluded is not None and (key == excluded or excluded in key.parents):
            return
        seen.add(key)
        found.append(candidate)

    for raw in paths:
        path = Path(raw)
        if path.is_file():
            if path.suffix.lower() == ".pdf":
                add(path)
        elif path.is_dir():
            for root, dirs, files in os.walk(path, onerror=lambda _err: None):
                # pastas ocultas (inclui .pdf2calibre) ficam de fora
                dirs[:] = sorted(name for name in dirs if not name.startswith("."))
                if not recursive:
                    dirs[:] = []
                for name in sorted(files):
                    if name.lower().endswith(".pdf") and not name.startswith("."):
                        add(Path(root) / name)
    return sorted(found, key=natural_key)


def build_entries(files: list[Path], options: Options, progress: ProgressFn | None = None,
                  cancel: threading.Event | None = None) -> list[BookEntry]:
    """Analisa os PDFs em paralelo, mantendo a ordem original."""
    entries: list[BookEntry] = []
    total = len(files)
    with ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        futures = [pool.submit(build_entry, path, options) for path in files]
        for index, future in enumerate(futures, start=1):
            if cancel is not None and cancel.is_set():
                for pending in futures:
                    pending.cancel()
                break
            entry = future.result()
            entries.append(entry)
            if progress:
                progress(index, total, entry.source.name)
    return entries


def _quality(entry: BookEntry, options: Options) -> tuple[bool, bool, bool]:
    """Quanto melhor o metadado, mais o livro merece ser o que fica entre cópias."""
    return (entry.author != options.unknown_author,
            entry.author_origin == "pdf",
            entry.title_origin == "pdf")


def mark_duplicates(entries: list[BookEntry], options: Options) -> int:
    """Marca cópias idênticas (mesmo hash) e avisa sobre mesmo título/autor.

    Entre cópias idênticas fica a de melhor metadado (empate: a primeira da lista).
    Devolve quantos arquivos foram marcados como duplicados.
    """
    groups: dict[str, list[BookEntry]] = {}
    for entry in entries:
        if entry.status in USABLE_STATUSES and entry.sha256:
            groups.setdefault(entry.sha256, []).append(entry)

    duplicates = 0
    survivors: set[int] = set()
    for group in groups.values():
        best = max(group, key=lambda item: _quality(item, options))
        survivors.add(id(best))
        for entry in group:
            if entry is best:
                continue
            duplicates += 1
            message = f"idêntico a {best.source.name}"
            if options.skip_duplicates:
                entry.fail(message, Status.DUPLICATE)
            else:
                entry.note(message)

    by_key: dict[tuple, BookEntry] = {}
    for entry in entries:  # na ordem original, só os que ficaram
        if id(entry) not in survivors:
            continue
        key = book_key(entry.title, entry.authors or [entry.author], entry.series,
                       entry.series_index)
        other = by_key.get(key)
        if other is not None:
            entry.status = Status.WARNING
            entry.note(f"mesmo título, autor e volume de {other.source.name} "
                       "(arquivo diferente)")
        else:
            by_key[key] = entry
    return duplicates


def book_key(title: str, authors: list[str], series: str = "",
             series_index: float | None = None) -> tuple:
    """Identidade de um livro: título + autores + série + volume (sem caixa e acentos).

    Volumes de uma coleção têm o mesmo título e autor ("One Punch Man", ONE) e só se
    diferenciam pelo número, então o volume precisa entrar na comparação.
    """
    def norm(text: str) -> str:
        return fold(re.sub(r"[\W_]+", " ", text or "")).strip()

    volume = series_index if series and series_index is not None else None
    return (norm(title), tuple(sorted(norm(a) for a in authors if a.strip())),
            norm(series) if volume is not None else "", volume)


def _same_content(path: Path, entry: BookEntry) -> bool:
    try:
        return path.stat().st_size == entry.size and sha256_file(path) == entry.sha256
    except OSError:
        return False


def _choose_target(base_dir: Path, stem: str, taken: set[str], entry: BookEntry,
                   folder_per_book: bool) -> tuple[Path, bool]:
    """Acha um caminho livre; devolve (caminho, já_existe_igual)."""
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f" ({attempt})"
        if folder_per_book:
            directory = base_dir.with_name(base_dir.name + suffix)
            candidate = directory / f"{stem}.pdf"
        else:
            candidate = base_dir / f"{stem}{suffix}.pdf"
        if str(candidate).casefold() not in taken:
            if not candidate.exists():
                return candidate, False
            if _same_content(candidate, entry):
                return candidate, True
        attempt += 1


def assign_targets(entries: list[BookEntry], dest_root: Path, options: Options) -> None:
    """Define a pasta e o nome final de cada livro (sem tocar no disco)."""
    for entry in entries:  # reavaliar caso o destino tenha mudado
        if entry.status is Status.EXISTS:
            entry.status, entry.selected = Status.READY, True
            entry.notes = [n for n in entry.notes if not n.startswith("já existe")]
        entry.target_dir = entry.target_file = None

    taken: set[str] = set()
    limit = options.max_name_length
    for entry in entries:
        if not entry.usable:
            continue
        stem = book_stem(entry.title, entry.author, limit)
        if options.folder_per_book:
            first_author = (entry.authors or [options.unknown_author])[0]
            base_dir = dest_root / sanitize_component(first_author, limit, "Unknown") \
                / sanitize_component(entry.title, limit, "Sem título")
        else:
            base_dir = dest_root
        target, already_there = _choose_target(
            base_dir, stem, taken, entry, options.folder_per_book)
        if already_there:
            entry.fail("já existe no destino", Status.EXISTS)
            continue
        taken.add(str(target).casefold())
        entry.target_dir, entry.target_file = target.parent, target


def sidecar_paths(target: Path, folder_per_book: bool) -> tuple[Path, Path]:
    """Caminhos do OPF e da capa de um livro: (opf, capa).

    O OPF sempre tem o mesmo nome do PDF ('Título - Autor.opf'): é o único nome
    que o Calibre procura quando adiciona o arquivo solto (Adicionar livros,
    arrastar, adição automática, `calibredb add`). Ao adicionar a pasta ele
    aceita qualquer .opf, então esse nome serve para todos os casos.
    """
    cover = target.parent / "cover.jpg" if folder_per_book else target.with_suffix(".jpg")
    return target.with_suffix(".opf"), cover


def summarize(entries: Iterable[BookEntry]) -> Counter:
    """Conta os livros por situação."""
    return Counter(entry.status for entry in entries)
