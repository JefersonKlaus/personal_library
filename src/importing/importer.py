"""Import: puts the reviewed PDFs into the library (the same one as the Gallery).

Each book is prepared in a temporary folder (`Título - Autor.pdf` + `.opf` with the
same name + cover) and added by the library tool, which reads all the metadata from
the OPF. The created ids are recorded for "Desfazer última importação".
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..core.files import copy_verified
from ..core.models import BookEntry, ImportOptions, Status
from ..core.paths import IMPORTS_DIR
from ..core.text import book_stem
from ..library.cli import AddResult, LibraryCli
from ..library.database import LibraryError, load_library
from ..library.opf import OpfData, render_opf
from ..pdf.pdf_cover import render_cover
from .analysis import book_key, entry_key

logger = logging.getLogger(__name__)
ProgressFn = Callable[[int, int, str], None]


@dataclass
class ImportReport:
    """Result of an import."""

    total: int = 0
    added: int = 0
    existing: int = 0
    failed: int = 0
    cancelled: bool = False
    book_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    record: Path | None = None

    def summary(self) -> str:
        text = f"{self.added} de {self.total} livro(s) adicionados à biblioteca"
        if self.existing:
            text += f", {self.existing} já estavam nela"
        if self.failed:
            text += f", {self.failed} com erro"
        if self.cancelled:
            text += " (cancelado)"
        return text + "."


def import_books(entries: list[BookEntry], library: Path, options: ImportOptions,
                 cli: LibraryCli, progress: ProgressFn | None = None,
                 cancel: threading.Event | None = None,
                 records_dir: Path = IMPORTS_DIR) -> ImportReport:
    """Adds the ticked books to the library and updates the state of each one."""
    library = Path(library)
    todo = [entry for entry in entries if entry.usable]
    report = ImportReport(total=len(todo))
    if options.skip_duplicates:
        report.existing += skip_volumes_already_in(library, todo)
        todo = [entry for entry in todo if entry.usable]
    with tempfile.TemporaryDirectory(prefix="personal-library-",
                                     ignore_cleanup_errors=True) as staging:
        for index, entry in enumerate(todo, start=1):
            if cancel is not None and cancel.is_set():
                report.cancelled = True
                break
            _import_one(entry, Path(staging) / str(index), library, options, cli, report)
            if progress:
                progress(index, len(todo), entry.title)
    if report.book_ids:
        titles = [entry.title for entry in todo if entry.status is Status.DONE]
        report.record = write_import_record(records_dir, library, report.book_ids, titles)
    return report


def _import_one(entry: BookEntry, folder: Path, library: Path, options: ImportOptions,
                cli: LibraryCli, report: ImportReport) -> None:
    tags = list(dict.fromkeys([*options.tags, *entry.tags]))
    try:
        book_file, cover = stage_book(entry, folder, tags)
    except Exception as exc:  # file gone, changed or disk full: only this book fails
        logger.exception("Failed to prepare %s", entry.source)
        _record_result(entry, AddResult(False, message=str(exc) or type(exc).__name__), report)
        return
    # The library compares title + author only and would refuse volume 2 of a collection;
    # volumes were already checked by title + author + series + volume (above).
    allow_duplicate = not options.skip_duplicates or entry.is_volume
    result = cli.add_book(library, book_file, entry, tags, cover, allow_duplicate)
    _record_result(entry, result, report)


def _record_result(entry: BookEntry, result: AddResult, report: ImportReport) -> None:
    if result.ok:
        report.added += 1
        report.book_ids += result.book_ids
        entry.status = Status.DONE
        entry.note(f"na biblioteca (id {', '.join(map(str, result.book_ids))})")
    elif result.duplicate:
        report.existing += 1
        entry.fail("já existe na biblioteca", Status.EXISTS)
    else:
        report.failed += 1
        entry.fail(result.message, Status.FAILED)
        report.errors.append(f"{entry.title}: {result.message}")


def stage_book(entry: BookEntry, folder: Path, tags: list[str]) -> tuple[Path, Path | None]:
    """Prepares the book in a folder: verified copy of the PDF, cover (1st page) and OPF."""
    folder.mkdir(parents=True, exist_ok=True)
    book_file = folder / f"{book_stem(entry.title, entry.author)}.pdf"
    copy_verified(entry.source, book_file, entry.sha256 or None)
    cover = folder / "cover.jpg"
    # With the OPF the library does not build a cover on its own, so it goes ready-made.
    has_cover = render_cover(book_file, cover)
    opf = render_opf(entry_opf_data(entry, tags), cover.name if has_cover else None)
    book_file.with_suffix(".opf").write_text(opf, encoding="utf-8")
    return book_file, cover if has_cover else None


def entry_opf_data(entry: BookEntry, tags: list[str]) -> OpfData:
    """Metadata of a PDF reviewed in the Import tab."""
    # Noon UTC: the date is shown in the local time zone, and midnight UTC would become
    # "Dec of the previous year" in Brazil (UTC-3).
    pubdate = f"{entry.year:04d}-01-01T12:00:00+00:00" if entry.year else ""
    return OpfData(
        title=entry.title, authors=entry.authors or [entry.author],
        uid_seed=entry.sha256 or str(entry.source), pubdate=pubdate,
        languages=[entry.language] if entry.language else [], tags=tags,
        publisher=entry.publisher, series=entry.series,
        series_index=entry.series_index if entry.series_index is not None else 1.0)


def skip_volumes_already_in(library: Path, entries: list[BookEntry]) -> int:
    """Marks the volumes the library already has (title + author + series + volume)."""
    volumes = [entry for entry in entries if entry.is_volume]
    if not volumes:
        return 0
    try:
        existing = {book_key(b.title, b.authors, b.series, b.series_index)
                    for b in load_library(library)}
    except LibraryError as exc:
        logger.warning("Could not check duplicates in %s: %s", library, exc)
        return 0
    skipped = 0
    for entry in volumes:
        if entry_key(entry) in existing:
            entry.fail("já existe na biblioteca (mesmo título, autor e volume)", Status.EXISTS)
            skipped += 1
    return skipped


# ---------------------------------------------------------------- undo

def write_import_record(folder: Path, library: Path, ids: list[int], titles: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"import-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    payload = {"version": 1, "created": datetime.now().isoformat(timespec="seconds"),
               "library": str(Path(library).resolve()), "ids": ids, "titles": titles}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_import(library: Path, folder: Path = IMPORTS_DIR) -> Path | None:
    """Latest import in this library that was not undone yet."""
    if not folder.is_dir():
        return None
    target = str(Path(library).resolve())
    for path in sorted(folder.glob("import-*.json"), key=lambda p: p.name, reverse=True):
        if path.name.endswith(".undone.json"):
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("library") == target:
                return path
        except (OSError, ValueError):
            continue
    return None


def undo_import(record: Path, cli: LibraryCli) -> tuple[int, str]:
    """Removes the books of the import (they go to the library recycle bin).

    Returns (how many, error message or "").
    """
    data = json.loads(Path(record).read_text(encoding="utf-8"))
    ids = [int(book_id) for book_id in data.get("ids", [])]
    ok, message = cli.remove_books(Path(data["library"]), ids)
    if not ok:
        return 0, message
    Path(record).rename(Path(record).with_suffix(".undone.json"))
    return len(ids), ""
