"""Reading the library (read-only): books and their metadata."""
import hashlib
import sqlite3
from datetime import datetime

import pytest

from src.core.text import html_to_text
from src.library import database, thumbnails
from src.library.manager import DATABASE_FILE


def _by_title(books):
    return {book.title: book for book in books}


def test_reads_books_with_all_their_metadata(make_library, tmp_path):
    root = make_library(tmp_path / "Biblioteca")
    books = _by_title(database.load_library(root))
    assert len(books) == 4
    dom = books["Dom Casmurro"]
    assert dom.authors == ["Machado de Assis"]
    assert dom.author_sort == "Assis, Machado de"
    assert dom.series_text == "Clássicos [1]"
    assert dom.tags == ["Brasil", "Romance"]  # alphabetical order
    assert dom.publisher == "Garnier"
    assert dom.languages == ["por", "eng"]  # respects item_order
    assert dom.identifiers == {"isbn": "9788535910667"}
    assert dom.year == 1899
    assert dom.added == datetime.fromisoformat("2024-01-10 10:00:00+00:00")
    assert html_to_text(dom.comments) == "Narrado por Bento.\nFim & tal."
    assert dom.cover_path(root) == root / "Machado de Assis" / "Dom Casmurro (1)" / "cover.jpg"
    assert dom.main_file(root).name == "Dom Casmurro - Machado de Assis.pdf"
    assert books["Física Básica"].authors == ["Ana Lima", "Rui Dias"]  # order of the link
    assert books["Física Básica"].authors_text == "Ana Lima & Rui Dias"


def test_undefined_pubdate_and_missing_cover(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    hobbit = _by_title(database.load_library(root))["The Hobbit"]
    assert hobbit.pubdate is None and hobbit.year is None  # 0101-01-01 = undefined
    assert hobbit.cover_path(root) is None
    assert thumbnails.thumbnail(hobbit, root, tmp_path / "cache") is None


def test_library_is_never_modified(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    db = root / DATABASE_FILE
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    files_before = sorted(p.name for p in root.iterdir())
    database.load_library(root)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in root.iterdir()) == files_before  # not -journal either


def test_reads_while_the_manager_holds_a_write_lock(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    writer = sqlite3.connect(root / DATABASE_FILE)
    writer.execute("BEGIN IMMEDIATE")  # the library program open, writing
    try:
        assert len(database.load_library(root)) == 4
    finally:
        writer.rollback()
        writer.close()


def test_network_share_falls_back_to_query_only(make_library, tmp_path, monkeypatch):
    """\\\\server\\folder becomes 'file://server/...', which SQLite refuses."""
    root = make_library(tmp_path / "lib")
    monkeypatch.setattr(database.Path, "as_uri", lambda self: "file://servidor/share/banco.db")
    assert len(database.load_library(root)) == 4


def test_old_library_without_optional_tables(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    conn = sqlite3.connect(root / DATABASE_FILE)
    conn.executescript("DROP TABLE books_languages_link; DROP TABLE languages; "
                       "DROP TABLE identifiers; DROP TABLE comments;")
    conn.close()
    books = _by_title(database.load_library(root))
    assert books["Dom Casmurro"].languages == []
    assert books["Dom Casmurro"].authors == ["Machado de Assis"]


def test_invalid_folders_raise_library_error(tmp_path):
    with pytest.raises(database.LibraryError, match=DATABASE_FILE):
        database.load_library(tmp_path)
    (tmp_path / DATABASE_FILE).write_bytes(b"isto nao e sqlite")
    with pytest.raises(database.LibraryError):
        database.load_library(tmp_path)


def test_year_for_books_before_1970(make_library, tmp_path):
    """On Windows astimezone() fails before 1970; the year still has to come out."""
    books = _by_title(database.load_library(make_library(tmp_path / "lib")))
    assert books["O Cortiço"].year == 1890


def test_folder_uses_forward_slash_paths(tmp_path):
    book = database.LibraryBook(id=1, title="T", path="Autor/Título (1)")
    assert book.folder(tmp_path) == tmp_path / "Autor" / "Título (1)"
    assert book.format_path(tmp_path, "pdf") is None
    assert database.LibraryBook(id=2, title="S", series="X", series_index=2.5).series_text == "X [2.5]"
