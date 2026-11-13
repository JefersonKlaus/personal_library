"""Search and order of the library books (gallery and export)."""
from __future__ import annotations

from datetime import datetime

from ..core.text import fold
from .database import LibraryBook

NO_SERIES = ""  # "Sem série" filter (None = every book)

SORTS = {
    "added": "Mais recentes",
    "title": "Título",
    "series": "Série e volume",
    "author": "Autor",
    "pubdate": "Publicação",
}


def _haystack(book: LibraryBook) -> str:
    parts = [book.title, *book.authors, *book.tags, book.series, book.publisher]
    return fold(" ".join(part for part in parts if part))


def search(books: list[LibraryBook], query: str) -> list[LibraryBook]:
    """Every word of the search has to appear in title, author, tag, series or publisher."""
    words = fold(query).split()
    if not words:
        return list(books)
    return [book for book in books if all(word in _haystack(book) for word in words)]


def sort_books(books: list[LibraryBook], key: str) -> list[LibraryBook]:
    """Sorts by 'added' (default), 'title', 'series', 'author' or 'pubdate'."""
    oldest = datetime.min

    def naive(value: datetime | None) -> datetime:
        return value.replace(tzinfo=None) if value else oldest

    if key == "title":  # same title (volumes): in volume order
        return sorted(books, key=lambda b: (fold(b.title_sort or b.title), fold(b.series),
                                            b.series_index))
    if key == "series":  # volumes in order (1, 2, ... 18); books without a series at the end
        return sorted(books, key=lambda b: (not b.series, fold(b.series), b.series_index,
                                            fold(b.title_sort or b.title)))
    if key == "author":
        return sorted(books, key=lambda b: (fold(b.author_sort), fold(b.title_sort)))
    if key == "pubdate":
        return sorted(books, key=lambda b: naive(b.pubdate), reverse=True)
    return sorted(books, key=lambda b: (naive(b.added), b.id), reverse=True)


def series_counts(books: list[LibraryBook]) -> list[tuple[str, int]]:
    """Series of the library and how many books each one has, in alphabetical order."""
    counts: dict[str, int] = {}
    for book in books:
        if book.series:
            counts[book.series] = counts.get(book.series, 0) + 1
    return sorted(counts.items(), key=lambda item: fold(item[0]))


def in_series(books: list[LibraryBook], series: str | None) -> list[LibraryBook]:
    """Books of a series; None = all; NO_SERIES = only those without a series."""
    if series is None:
        return list(books)
    return [book for book in books if book.series == series]
