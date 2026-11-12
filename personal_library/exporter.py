"""Exportar: copia livros da biblioteca para outra pasta, com os metadados ao lado.

Cada livro vira `Autor/Título/Título - Autor.pdf` (e os outros formatos que tiver),
com `Título - Autor.opf` (todos os metadados) e `cover.jpg`. A pasta pode ser
adicionada em outra biblioteca. A biblioteca de origem só é lida, nunca alterada.
"""
from __future__ import annotations

import logging
import os
import shutil
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .files import (CreatedFiles, FileOperationError, copy_verified, ensure_free_space,
                    make_dirs, remove_empty_dirs, write_manifest)
from .library.database import LibraryBook
from .library.location import find_library_root
from .library.opf import OpfData, render_opf
from .models import Status
from .text import book_stem, fold, sanitize_component

logger = logging.getLogger(__name__)
ProgressFn = Callable[[int, int, str], None]


@dataclass
class ExportOptions:
    """Como os livros são gravados no destino."""

    folder_per_book: bool = True  # Autor/Título/arquivo
    write_opf: bool = True
    include_cover: bool = True
    max_name_length: int = 80
    dry_run: bool = False


@dataclass
class ExportItem:
    """Um livro da biblioteca e para onde cada arquivo dele vai."""

    book: LibraryBook
    files: list[tuple[Path, Path]] = field(default_factory=list)  # (origem, destino)
    opf: Path | None = None
    cover: tuple[Path, Path] | None = None
    status: Status = Status.READY
    message: str = ""

    @property
    def target(self) -> Path | None:
        return self.files[0][1] if self.files else None


@dataclass
class ExportReport:
    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    manifest: Path | None = None
    errors: list[str] = field(default_factory=list)


def book_opf_data(book: LibraryBook) -> OpfData:
    """Todos os metadados do livro, como estão na biblioteca."""
    return OpfData(
        title=book.title, authors=book.authors or ["Unknown"],
        author_sort=book.author_sort, title_sort=book.title_sort,
        uid_seed=f"library-book:{book.id}:{book.title}",
        pubdate=book.pubdate.isoformat() if book.pubdate else "",
        languages=book.languages, tags=book.tags, series=book.series,
        series_index=book.series_index, publisher=book.publisher,
        identifiers=book.identifiers, comments=book.comments)


# ---------------------------------------------------------------- planejamento

def _source_files(book: LibraryBook, library: Path) -> list[tuple[str, Path]]:
    """Formatos que existem no disco, com o PDF primeiro."""
    found = []
    for fmt in sorted(book.formats, key=lambda item: (item != "PDF", item)):
        path = book.format_path(library, fmt)
        if path is not None and path.is_file():
            found.append((fmt, path))
    return found


def _same_size(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size
    except OSError:
        return False


def _free_targets(base: Path, stem: str, sources: list[tuple[str, Path]], taken: set[str],
                  folder_per_book: bool) -> tuple[list[tuple[Path, Path]], bool]:
    """Acha caminhos livres (acrescenta ' (2)', ' (3)'...). Devolve (destinos, já_existe)."""
    attempt = 1
    while True:
        suffix = "" if attempt == 1 else f" ({attempt})"
        folder, name = (base.with_name(base.name + suffix), stem) if folder_per_book \
            else (base, stem + suffix)
        targets = [(src, folder / f"{name}.{fmt.lower()}") for fmt, src in sources]
        if not any(str(target).casefold() in taken for _src, target in targets):
            existing = [(src, target) for src, target in targets if target.exists()]
            if not existing:
                return targets, False
            if len(existing) == len(targets) and all(_same_size(s, t) for s, t in existing):
                return targets, True
        attempt += 1


def plan_export(books: list[LibraryBook], library: Path, dest_root: Path,
                options: ExportOptions) -> list[ExportItem]:
    """Decide o caminho de cada arquivo no destino (sem tocar no disco)."""
    library, dest_root = Path(library), Path(dest_root)
    limit = options.max_name_length
    taken: set[str] = set()
    # Volumes com o mesmo título e autor ("One Punch Man", ONE) levam o volume no
    # nome do arquivo; livros comuns ficam com o nome de sempre.
    same_name = Counter((fold(b.title), fold(b.authors_text)) for b in books)
    items: list[ExportItem] = []
    for book in books:
        item = ExportItem(book)
        items.append(item)
        sources = _source_files(book, library)
        if not sources:
            item.status, item.message = Status.ERROR, "nenhum arquivo do livro na biblioteca"
            continue
        name = book.title
        if book.series and same_name[(fold(book.title), fold(book.authors_text))] > 1:
            name = f"{book.title} - Vol. {book.series_index:g}"
        base = dest_root / sanitize_component((book.authors or ["Unknown"])[0], limit, "Unknown") \
            / sanitize_component(name, limit, "Sem título") if options.folder_per_book else dest_root
        item.files, exists = _free_targets(base, book_stem(name, book.authors_text, limit),
                                           sources, taken, options.folder_per_book)
        taken.update(str(target).casefold() for _src, target in item.files)
        if exists:
            item.status, item.message = Status.EXISTS, "já existe no destino"
        _plan_sidecars(item, library, options)
    return items


def _plan_sidecars(item: ExportItem, library: Path, options: ExportOptions) -> None:
    main_target = item.target
    if options.write_opf:
        item.opf = main_target.with_suffix(".opf")
    cover = item.book.cover_path(library)
    if options.include_cover and cover is not None:
        item.cover = (cover, main_target.parent / "cover.jpg" if options.folder_per_book
                      else main_target.with_suffix(".jpg"))


# ---------------------------------------------------------------- cópia

def _export_one(item: ExportItem) -> CreatedFiles:
    """Copia os arquivos (como .part), grava capa e OPF e só então dá o nome final:
    quem vigia a pasta nunca vê o livro sem os metadados ao lado."""
    created = make_dirs(item.target.parent)
    temps = [(target.with_name(target.name + ".part"), target) for _src, target in item.files]
    written: list[Path] = []
    try:
        for (source, _target), (temp, _final) in zip(item.files, temps):
            copy_verified(source, temp)
        if item.cover is not None:
            written.append(item.cover[1])
            shutil.copy2(*item.cover)
        if item.opf is not None:
            written.append(item.opf)
            cover_name = item.cover[1].name if item.cover else None
            item.opf.write_text(render_opf(book_opf_data(item.book), cover_name),
                                encoding="utf-8")
        for temp, target in temps:
            os.replace(temp, target)
            written.append(target)
    except Exception:
        for path in [temp for temp, _t in temps] + written:
            path.unlink(missing_ok=True)
        remove_empty_dirs(created)
        raise
    return CreatedFiles([str(path) for path in written], created)


def export_books(books: list[LibraryBook], library: Path, dest_root: Path,
                 options: ExportOptions, progress: ProgressFn | None = None,
                 cancel: threading.Event | None = None) -> tuple[ExportReport, list[ExportItem]]:
    """Copia os livros para `dest_root`. Devolve o relatório e a situação de cada livro."""
    library, dest_root = Path(library), Path(dest_root)
    inside = find_library_root(dest_root)
    if inside is not None:
        raise FileOperationError(
            f"O destino fica dentro de uma biblioteca ({inside}). Exporte para uma pasta "
            "comum; para colocar livros numa biblioteca, use a aba Importar.")
    items = plan_export(books, library, dest_root, options)
    todo = [item for item in items if item.status is Status.READY]
    report = ExportReport(total=len(todo), skipped=len(items) - len(todo))
    if not options.dry_run and todo:
        dest_root.mkdir(parents=True, exist_ok=True)
        ensure_free_space(dest_root, sum(src.stat().st_size for item in todo
                                         for src, _t in item.files))
    records: list[CreatedFiles] = []
    for index, item in enumerate(todo, start=1):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        try:
            if not options.dry_run:
                records.append(_export_one(item))
                item.status = Status.DONE
            report.done += 1
        except Exception as exc:  # um livro com problema não para o lote
            logger.exception("Falha ao exportar %s", item.book.title)
            item.status, item.message = Status.FAILED, str(exc) or type(exc).__name__
            report.failed += 1
            report.errors.append(f"{item.book.title}: {item.message}")
        if progress:
            progress(index, report.total, item.book.title)
    if records:
        report.manifest = write_manifest(dest_root, records)
    return report, items
