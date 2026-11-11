"""Exportar: copia livros da biblioteca do Calibre para outra pasta, no formato do Calibre.

Cada livro vira `Autor/Título/Título - Autor.pdf` (e os outros formatos que tiver),
com `Título - Autor.opf` (todos os metadados) e `cover.jpg`. Essa pasta pode ser
adicionada em outro Calibre com "Adicionar de pastas e subpastas" ou arrastando os
arquivos. A biblioteca de origem só é lida, nunca alterada.
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

from .calibre import find_library_root
from .library import LibraryBook, fold
from .metadata import sha256_file
from .models import Mode, OperationRecord, Report, Status
from .naming import book_stem, sanitize_component
from .opf import OpfData, render_opf
from .organizer import OrganizerError, _make_dirs, _remove_empty, write_manifest

logger = logging.getLogger(__name__)
ProgressFn = Callable[[int, int, str], None]


@dataclass
class ExportOptions:
    """Como os livros são gravados no destino."""

    folder_per_book: bool = True  # Autor/Título/arquivo, como o Calibre
    write_opf: bool = True
    include_cover: bool = True
    verify_hash: bool = True
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


def book_opf_data(book: LibraryBook) -> OpfData:
    """Todos os metadados do livro, como estão no banco do Calibre."""
    return OpfData(
        title=book.title, authors=book.authors or ["Unknown"],
        author_sort=book.author_sort, title_sort=book.title_sort,
        uid_seed=f"library-book:{book.id}:{book.title}",
        pubdate=book.pubdate.isoformat() if book.pubdate else "",
        languages=book.languages, tags=book.tags, series=book.series,
        series_index=book.series_index, publisher=book.publisher,
        identifiers=book.identifiers, comments=book.comments)


def _source_files(book: LibraryBook, library: Path) -> list[tuple[str, Path]]:
    """Formatos que existem no disco, com o PDF primeiro."""
    found = []
    for fmt in sorted(book.formats, key=lambda item: (item != "PDF", item)):
        path = book.format_path(library, fmt)
        if path is not None and path.is_file():
            found.append((fmt, path))
    return found


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.stat().st_size == b.stat().st_size
    except OSError:
        return False


def plan_export(books: list[LibraryBook], library: Path, dest_root: Path,
                options: ExportOptions) -> list[ExportItem]:
    """Decide o caminho de cada arquivo no destino (sem tocar no disco)."""
    library, dest_root = Path(library), Path(dest_root)
    taken: set[str] = set()
    items: list[ExportItem] = []
    limit = options.max_name_length
    # Volumes com o mesmo título e autor ("One Punch Man", ONE) levam o volume no
    # nome do arquivo; livros comuns ficam com o nome de sempre.
    same_name = Counter((fold(b.title), fold(b.authors_text)) for b in books)
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
        stem = book_stem(name, book.authors_text, limit)
        if options.folder_per_book:
            base = dest_root / sanitize_component((book.authors or ["Unknown"])[0], limit, "Unknown") \
                / sanitize_component(name, limit, "Sem título")
        attempt = 1
        while True:
            suffix = "" if attempt == 1 else f" ({attempt})"
            if options.folder_per_book:
                folder, name = base.with_name(base.name + suffix), stem
            else:
                folder, name = dest_root, stem + suffix
            targets = [(src, folder / f"{name}.{fmt.lower()}") for fmt, src in sources]
            keys = [str(target).casefold() for _src, target in targets]
            if not any(key in taken for key in keys):
                existing = [(src, target) for src, target in targets if target.exists()]
                if not existing:
                    break
                if len(existing) == len(targets) and all(_same_file(s, t) for s, t in existing):
                    item.status, item.message = Status.EXISTS, "já existe no destino"
                    break
            attempt += 1
        taken.update(keys)
        item.files = targets
        main_target = targets[0][1]
        if options.write_opf:
            item.opf = main_target.with_suffix(".opf")
        cover = book.cover_path(library)
        if options.include_cover and cover is not None:
            cover_target = main_target.parent / "cover.jpg" if options.folder_per_book \
                else main_target.with_suffix(".jpg")
            item.cover = (cover, cover_target)
    return items


def _check_space(dest_root: Path, items: list[ExportItem]) -> None:
    needed = sum(src.stat().st_size for item in items for src, _t in item.files)
    free = shutil.disk_usage(dest_root).free
    if needed * 1.02 > free:
        raise OrganizerError(
            f"Espaço insuficiente no destino: precisa de {needed / 1e6:.0f} MB "
            f"e há {free / 1e6:.0f} MB livres.")


def _copy_verified(source: Path, temp: Path, verify_hash: bool) -> None:
    shutil.copy2(source, temp)
    if temp.stat().st_size != source.stat().st_size:
        raise OrganizerError(f"o tamanho de {source.name} mudou ao copiar")
    if verify_hash and sha256_file(temp) != sha256_file(source):
        raise OrganizerError(f"{source.name} ficou diferente após copiar")


def _export_one(item: ExportItem, options: ExportOptions) -> OperationRecord:
    assert item.target is not None
    created = _make_dirs(item.target.parent)
    temps: list[tuple[Path, Path]] = []
    written: list[Path] = []
    try:
        for source, target in item.files:
            temp = target.with_name(target.name + ".part")
            temps.append((temp, target))
            _copy_verified(source, temp, options.verify_hash)
        # OPF e capa antes dos livros aparecerem com o nome final (adição automática).
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
        for temp, _target in temps:
            temp.unlink(missing_ok=True)
        for path in written:
            path.unlink(missing_ok=True)
        _remove_empty(created)
        raise
    extra = [str(target) for _s, target in item.files[1:]]
    sidecars = extra + [str(path) for path in (item.cover[1] if item.cover else None, item.opf)
                        if path is not None]
    return OperationRecord(str(item.files[0][0]), str(item.target), Mode.COPY.value,
                           sidecars, created)


def export_books(books: list[LibraryBook], library: Path, dest_root: Path,
                 options: ExportOptions, progress: ProgressFn | None = None,
                 cancel: threading.Event | None = None) -> tuple[Report, list[ExportItem]]:
    """Copia os livros para `dest_root`. Devolve o relatório e a situação de cada livro."""
    library, dest_root = Path(library), Path(dest_root)
    inside = find_library_root(dest_root)
    if inside is not None:
        raise OrganizerError(
            f"O destino fica dentro de uma biblioteca do Calibre ({inside}). Exporte para "
            "uma pasta comum; para colocar os livros em outra biblioteca, use a aba Importar "
            "ou 'Adicionar livros' no Calibre.")
    items = plan_export(books, library, dest_root, options)
    todo = [item for item in items if item.status is Status.READY]
    report = Report(total=len(todo), dry_run=options.dry_run, skipped=len(items) - len(todo))
    if not options.dry_run and todo:
        dest_root.mkdir(parents=True, exist_ok=True)
        _check_space(dest_root, todo)
    for index, item in enumerate(todo, start=1):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        try:
            if not options.dry_run:
                report.operations.append(_export_one(item, options))
                item.status = Status.DONE
            report.done += 1
        except Exception as exc:  # um livro com problema não para o lote
            logger.exception("Falha ao exportar %s", item.book.title)
            item.status, item.message = Status.FAILED, str(exc) or type(exc).__name__
            report.failed += 1
            report.errors.append(f"{item.book.title}: {item.message}")
        if progress:
            progress(index, report.total, item.book.title)
    if report.operations:
        report.manifest = write_manifest(dest_root, report.operations)
    return report, items
