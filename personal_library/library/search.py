"""Busca e ordem dos livros da biblioteca (galeria e exportação)."""
from __future__ import annotations

from datetime import datetime

from ..text import fold
from .database import LibraryBook

NO_SERIES = ""  # filtro "Sem série" (None = todos os livros)

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
    """Todas as palavras da busca precisam aparecer em título, autor, etiqueta, série ou editora."""
    words = fold(query).split()
    if not words:
        return list(books)
    return [book for book in books if all(word in _haystack(book) for word in words)]


def sort_books(books: list[LibraryBook], key: str) -> list[LibraryBook]:
    """Ordena por 'added' (padrão), 'title', 'series', 'author' ou 'pubdate'."""
    oldest = datetime.min

    def naive(value: datetime | None) -> datetime:
        return value.replace(tzinfo=None) if value else oldest

    if key == "title":  # mesmo título (volumes): em ordem de volume
        return sorted(books, key=lambda b: (fold(b.title_sort or b.title), fold(b.series),
                                            b.series_index))
    if key == "series":  # volumes em ordem (1, 2, ... 18); livros sem série no fim
        return sorted(books, key=lambda b: (not b.series, fold(b.series), b.series_index,
                                            fold(b.title_sort or b.title)))
    if key == "author":
        return sorted(books, key=lambda b: (fold(b.author_sort), fold(b.title_sort)))
    if key == "pubdate":
        return sorted(books, key=lambda b: naive(b.pubdate), reverse=True)
    return sorted(books, key=lambda b: (naive(b.added), b.id), reverse=True)


def series_counts(books: list[LibraryBook]) -> list[tuple[str, int]]:
    """Séries da biblioteca e quantos livros cada uma tem, em ordem alfabética."""
    counts: dict[str, int] = {}
    for book in books:
        if book.series:
            counts[book.series] = counts.get(book.series, 0) + 1
    return sorted(counts.items(), key=lambda item: fold(item[0]))


def in_series(books: list[LibraryBook], series: str | None) -> list[LibraryBook]:
    """Livros de uma série; None = todos; NO_SERIES = só os que não têm série."""
    if series is None:
        return list(books)
    return [book for book in books if book.series == series]
