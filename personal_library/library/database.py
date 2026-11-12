"""Leitura somente leitura da biblioteca: o banco de dados e as pastas dos livros.

Cada livro fica numa pasta `Autor/Título (id)/` com os arquivos e `cover.jpg`; os
metadados ficam no banco SQLite da biblioteca. O banco é aberto em modo `ro`,
então nada aqui altera a biblioteca.
"""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .manager import DATABASE_FILE

logger = logging.getLogger(__name__)


class LibraryError(Exception):
    """A pasta não é uma biblioteca ou o banco não pôde ser lido."""


@dataclass
class LibraryBook:
    """Um livro da biblioteca."""

    id: int
    title: str
    authors: list[str] = field(default_factory=list)
    title_sort: str = ""
    author_sort: str = ""
    path: str = ""  # pasta relativa à biblioteca, sempre com '/'
    has_cover: bool = False
    added: datetime | None = None
    pubdate: datetime | None = None
    series: str = ""
    series_index: float = 1.0
    publisher: str = ""
    tags: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    formats: dict[str, str] = field(default_factory=dict)  # 'PDF' -> nome do arquivo
    identifiers: dict[str, str] = field(default_factory=dict)
    comments: str = ""

    @property
    def authors_text(self) -> str:
        return " & ".join(self.authors) or "Desconhecido"

    @property
    def year(self) -> int | None:
        """Ano de publicação no fuso local (a biblioteca guarda em UTC)."""
        if self.pubdate is None:
            return None
        # Soma o deslocamento atual em vez de astimezone(): no Windows,
        # astimezone() falha para datas antes de 1970 (livros antigos).
        offset = datetime.now().astimezone().utcoffset() or timedelta()
        return (self.pubdate + offset).year

    @property
    def series_text(self) -> str:
        if not self.series:
            return ""
        index = f"{self.series_index:g}"
        return f"{self.series} [{index}]"

    def folder(self, library: Path) -> Path:
        return Path(library).joinpath(*self.path.split("/"))

    def cover_path(self, library: Path) -> Path | None:
        if not self.has_cover:
            return None
        cover = self.folder(library) / "cover.jpg"
        return cover if cover.is_file() else None

    def format_path(self, library: Path, fmt: str) -> Path | None:
        name = self.formats.get(fmt.upper())
        if not name:
            return None
        return self.folder(library) / f"{name}.{fmt.lower()}"

    def main_file(self, library: Path) -> Path | None:
        """O arquivo para abrir: PDF se houver, senão o primeiro formato existente."""
        order = sorted(self.formats, key=lambda fmt: (fmt != "PDF", fmt))
        for fmt in order:
            path = self.format_path(library, fmt)
            if path is not None and path.is_file():
                return path
        return None


# ---------------------------------------------------------------- leitura

def _parse_date(raw: object) -> datetime | None:
    """Datas da biblioteca: '2024-05-01 10:00:00.123+00:00'; ano 101 = indefinida."""
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return None if value.year <= 101 else value


def _connect(library: Path) -> sqlite3.Connection:
    db = Path(library) / DATABASE_FILE
    if not db.is_file():
        raise LibraryError(f"{library} não é uma biblioteca (falta o {DATABASE_FILE}).")
    try:
        # Somente leitura: nada que o app faça pode alterar a biblioteca.
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        # URIs de compartilhamentos de rede (\\servidor\pasta) não são aceitas pelo
        # SQLite; abre pelo caminho e bloqueia qualquer escrita com query_only.
        try:
            conn = sqlite3.connect(str(db), timeout=10)
            conn.execute("PRAGMA query_only = ON")
        except sqlite3.Error as exc:
            raise LibraryError(f"Não foi possível ler {db}: {exc}") from exc
    try:
        conn.execute("SELECT 1 FROM books LIMIT 1")
    except sqlite3.Error as exc:
        conn.close()
        raise LibraryError(f"Não foi possível ler {db}: {exc}") from exc
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def load_library(library: Path | str) -> list[LibraryBook]:
    """Lê todos os livros da biblioteca (sem alterar nada)."""
    library = Path(library)
    conn = _connect(library)
    try:
        tables = _tables(conn)
        books: dict[int, LibraryBook] = {}
        rows = conn.execute(
            "SELECT id, title, sort, author_sort, path, has_cover, timestamp, pubdate, "
            "series_index FROM books")
        for book_id, title, sort, a_sort, path, cover, added, pub, s_index in rows:
            books[book_id] = LibraryBook(
                id=book_id, title=title or "Sem título", title_sort=sort or title or "",
                author_sort=a_sort or "", path=(path or "").replace("\\", "/"),
                has_cover=bool(cover), added=_parse_date(added), pubdate=_parse_date(pub),
                series_index=float(s_index or 1.0))

        if {"books_authors_link", "authors"} <= tables:
            for book_id, name in conn.execute(
                    "SELECT l.book, a.name FROM books_authors_link l "
                    "JOIN authors a ON a.id = l.author ORDER BY l.id"):
                if book_id in books:
                    books[book_id].authors.append(name.replace("|", ","))
        if {"books_tags_link", "tags"} <= tables:
            tags: dict[int, list[str]] = defaultdict(list)
            for book_id, name in conn.execute(
                    "SELECT l.book, t.name FROM books_tags_link l JOIN tags t ON t.id = l.tag"):
                tags[book_id].append(name)
            for book_id, names in tags.items():
                if book_id in books:
                    books[book_id].tags = sorted(names, key=str.casefold)
        if {"books_series_link", "series"} <= tables:
            for book_id, name in conn.execute(
                    "SELECT l.book, s.name FROM books_series_link l JOIN series s ON s.id = l.series"):
                if book_id in books:
                    books[book_id].series = name
        if {"books_publishers_link", "publishers"} <= tables:
            for book_id, name in conn.execute(
                    "SELECT l.book, p.name FROM books_publishers_link l "
                    "JOIN publishers p ON p.id = l.publisher"):
                if book_id in books:
                    books[book_id].publisher = name
        if {"books_languages_link", "languages"} <= tables:
            for book_id, code in conn.execute(
                    "SELECT l.book, g.lang_code FROM books_languages_link l "
                    "JOIN languages g ON g.id = l.lang_code ORDER BY l.item_order"):
                if book_id in books:
                    books[book_id].languages.append(code)
        if "data" in tables:
            for book_id, fmt, name in conn.execute("SELECT book, format, name FROM data"):
                if book_id in books:
                    books[book_id].formats[fmt.upper()] = name
        if "identifiers" in tables:
            for book_id, kind, value in conn.execute("SELECT book, type, val FROM identifiers"):
                if book_id in books:
                    books[book_id].identifiers[kind] = value
        if "comments" in tables:
            for book_id, text in conn.execute("SELECT book, text FROM comments"):
                if book_id in books:
                    books[book_id].comments = text or ""
    except sqlite3.Error as exc:
        raise LibraryError(f"Erro ao ler a biblioteca: {exc}") from exc
    finally:
        conn.close()
    return list(books.values())
