"""Renaming books and series of the library (through the library tool)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.text import fold, normalize_text, title_sort
from .cli import LibraryCli
from .database import LibraryBook

ProgressFn = Callable[[int, int, str], None]


class RenameError(ValueError):
    """Invalid name (message ready to be shown)."""


def clean_name(text: str | None, what: str) -> str:
    """Collapses repeated spaces; an empty name is not accepted."""
    name = normalize_text(text or "")
    if not name:
        raise RenameError(f"O nome {what} não pode ficar vazio.")
    return name


def title_fields(title: str) -> dict[str, str]:
    """Title and sort name together: the title alone would keep the old sort name
    ('O Hobbit' would still be sorted as 'Hobbit, The')."""
    return {"title": title, "sort": title_sort(title)}


def rename_book(cli: LibraryCli, library: Path, book: LibraryBook, new_title: str) -> tuple[bool, str]:
    """Renames a book. Returns (ok, error)."""
    title = clean_name(new_title, "do livro")
    if title == book.title:
        return True, ""
    return cli.set_fields(library, book.id, title_fields(title))


def titles_like_series(books: list[LibraryBook], series: str) -> int:
    """How many books of the series have the same title as the series name (imported volumes)."""
    return sum(1 for book in books if book.series == series and fold(book.title) == fold(series))


@dataclass
class RenameReport:
    total: int = 0
    done: int = 0
    failed: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)


def rename_series(cli: LibraryCli, library: Path, books: list[LibraryBook], old: str, new: str,
                  rename_titles: bool = False, progress: ProgressFn | None = None,
                  cancel: threading.Event | None = None) -> RenameReport:
    """Moves every book of series `old` to `new` (one book at a time).

    With `rename_titles`, the titles equal to the old series name are changed too.
    If `new` already exists, the books become part of it.
    """
    new = clean_name(new, "da série")
    members = [book for book in books if book.series == old]
    report = RenameReport(total=len(members))
    for index, book in enumerate(members, start=1):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        fields = {"series": new}
        if rename_titles and fold(book.title) == fold(old):
            fields.update(title_fields(new))
        ok, error = cli.set_fields(library, book.id, fields)
        if ok:
            report.done += 1
        else:
            report.failed += 1
            report.errors.append(f"{book.title}: {error}")
        if progress:
            progress(index, report.total, book.title)
    return report
