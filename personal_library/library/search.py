"""Busca e ordem dos livros da biblioteca (galeria e exportação)."""
from __future__ import annotations

from datetime import datetime

from ..text import fold
from .database import LibraryBook

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
