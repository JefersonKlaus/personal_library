"""Leitura (somente leitura) de uma biblioteca do Calibre para a galeria.

O Calibre guarda tudo em `metadata.db` (SQLite) e cada livro numa pasta
`Autor/Título (id)/` com os arquivos, `cover.jpg` e `metadata.opf`. Aqui só
lemos: o banco é aberto em modo `ro`, então o app nunca altera a biblioteca.
"""
from __future__ import annotations

import hashlib
import io
import logging
import sqlite3
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

DB_NAME = "metadata.db"
THUMB_SIZE = (200, 300)  # 2:3, proporção de capa de livro

SORTS = {
    "added": "Mais recentes",
    "title": "Título",
    "series": "Série e volume",
    "author": "Autor",
    "pubdate": "Publicação",
}


class LibraryError(Exception):
    """A pasta não é uma biblioteca do Calibre ou o banco não pôde ser lido."""


@dataclass
class LibraryBook:
    """Um livro como o Calibre o mostra."""

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
        """Ano de publicação no fuso local (o Calibre guarda em UTC)."""
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
    """Datas do Calibre: '2024-05-01 10:00:00.123+00:00'; ano 101 = indefinida."""
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(str(raw))
    except ValueError:
        return None
    return None if value.year <= 101 else value


def _connect(library: Path) -> sqlite3.Connection:
    db = Path(library) / DB_NAME
    if not db.is_file():
        raise LibraryError(f"{library} não é uma biblioteca do Calibre (falta o {DB_NAME}).")
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


# ---------------------------------------------------------------- busca e ordem

def fold(text: str) -> str:
    """Minúsculas e sem acentos: 'Cortiço' e 'cortico' se encontram."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


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
    """Ordena como o Calibre: 'added' (padrão), 'title', 'author' ou 'pubdate'."""
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


# ---------------------------------------------------------------- capas

def thumbnail(book: LibraryBook, library: Path, cache_dir: Path | None,
              size: tuple[int, int] = THUMB_SIZE) -> bytes | None:
    """JPEG pequeno da capa (com cache em disco). Nunca levanta exceção.

    Sem Pillow devolve a capa original, que funciona, só é mais pesada.
    """
    cover = book.cover_path(library)
    if cover is None:
        return None
    try:
        stat = cover.stat()
        key = f"{Path(library).resolve()}|{book.id}|{stat.st_mtime_ns}|{stat.st_size}|{size}"
        cached = None
        if cache_dir is not None:
            cached = Path(cache_dir) / f"{hashlib.sha1(key.encode()).hexdigest()}.jpg"
            if cached.is_file():
                return cached.read_bytes()
        try:
            from PIL import Image
        except ImportError:
            return cover.read_bytes()
        with Image.open(cover) as image:
            image = image.convert("RGB")
            image.thumbnail(size)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=82)
        data = buffer.getvalue()
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            temp = cached.with_suffix(".part")
            temp.write_bytes(data)
            temp.replace(cached)
        return data
    except Exception as exc:  # capa corrompida, sem permissão, disco cheio...
        logger.warning("Capa ilegível de %s: %s", book.title, exc)
        return None


def plain_text(html: str) -> str:
    """Comentários do Calibre vêm em HTML; a galeria mostra só o texto."""
    import html as html_lib
    import re

    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
