"""Renomear livros e séries da biblioteca (pela ferramenta da biblioteca)."""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .library.cli import LibraryCli
from .library.database import LibraryBook
from .text import fold, normalize_text, title_sort

ProgressFn = Callable[[int, int, str], None]


class RenameError(ValueError):
    """Nome inválido (mensagem pronta para mostrar)."""


def clean_name(text: str | None, what: str) -> str:
    """Tira espaços repetidos; nome vazio não é aceito."""
    name = normalize_text(text or "")
    if not name:
        raise RenameError(f"O nome {what} não pode ficar vazio.")
    return name


def title_fields(title: str) -> dict[str, str]:
    """Título e ordenação juntos: só o título deixaria a ordenação antiga
    ('O Hobbit' continuaria ordenado como 'Hobbit, The')."""
    return {"title": title, "sort": title_sort(title)}


def rename_book(cli: LibraryCli, library: Path, book: LibraryBook, new_title: str) -> tuple[bool, str]:
    """Renomeia um livro. Devolve (ok, erro)."""
    title = clean_name(new_title, "do livro")
    if title == book.title:
        return True, ""
    return cli.set_fields(library, book.id, title_fields(title))


def titles_like_series(books: list[LibraryBook], series: str) -> int:
    """Quantos livros da série têm o título igual ao nome dela (volumes importados)."""
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
    """Passa todos os livros da série `old` para `new` (um livro por vez).

    Com `rename_titles`, os títulos iguais ao nome antigo da série também mudam.
    Se `new` já existir, os livros passam a fazer parte dela.
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
