import hashlib
import sqlite3
import sys
from datetime import datetime

import pytest

from personal_library.library import database, search, thumbnails
from personal_library.library.manager import DATABASE_FILE
from personal_library.text import html_to_text


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
    assert dom.tags == ["Brasil", "Romance"]  # ordem alfabética
    assert dom.publisher == "Garnier"
    assert dom.languages == ["por", "eng"]  # respeita item_order
    assert dom.identifiers == {"isbn": "9788535910667"}
    assert dom.year == 1899
    assert dom.added == datetime.fromisoformat("2024-01-10 10:00:00+00:00")
    assert html_to_text(dom.comments) == "Narrado por Bento.\nFim & tal."
    assert dom.cover_path(root) == root / "Machado de Assis" / "Dom Casmurro (1)" / "cover.jpg"
    assert dom.main_file(root).name == "Dom Casmurro - Machado de Assis.pdf"
    assert books["Física Básica"].authors == ["Ana Lima", "Rui Dias"]  # ordem do link
    assert books["Física Básica"].authors_text == "Ana Lima & Rui Dias"


def test_undefined_pubdate_and_missing_cover(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    hobbit = _by_title(database.load_library(root))["The Hobbit"]
    assert hobbit.pubdate is None and hobbit.year is None  # 0101-01-01 = indefinida
    assert hobbit.cover_path(root) is None
    assert thumbnails.thumbnail(hobbit, root, tmp_path / "cache") is None


def test_library_is_never_modified(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    db = root / DATABASE_FILE
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    files_before = sorted(p.name for p in root.iterdir())
    database.load_library(root)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
    assert sorted(p.name for p in root.iterdir()) == files_before  # nem -journal


def test_reads_while_the_manager_holds_a_write_lock(make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    writer = sqlite3.connect(root / DATABASE_FILE)
    writer.execute("BEGIN IMMEDIATE")  # o programa da biblioteca aberto, gravando
    try:
        assert len(database.load_library(root)) == 4
    finally:
        writer.rollback()
        writer.close()


def test_network_share_falls_back_to_query_only(make_library, tmp_path, monkeypatch):
    """\\\\servidor\\pasta vira 'file://servidor/...', que o SQLite recusa."""
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


def test_search_ignores_case_and_accents(make_library, tmp_path):
    books = database.load_library(make_library(tmp_path / "lib"))
    titles = lambda query: sorted(b.title for b in search.search(books, query))  # noqa: E731
    assert titles("cortico") == ["O Cortiço"]
    assert titles("MACHADO") == ["Dom Casmurro"]
    assert titles("romance brasil") == ["Dom Casmurro"]  # todas as palavras
    assert titles("clássicos") == ["Dom Casmurro", "O Cortiço"]  # série
    assert titles("garnier") == ["Dom Casmurro"]  # editora
    assert titles("  ") == sorted(b.title for b in books)
    assert titles("nada disso") == []


def test_sort_orders(make_library, tmp_path):
    books = database.load_library(make_library(tmp_path / "lib"))
    order = lambda key: [b.title for b in search.sort_books(books, key)]  # noqa: E731
    assert order("added") == ["Física Básica", "O Cortiço", "The Hobbit", "Dom Casmurro"]
    assert order("title") == ["Dom Casmurro", "Física Básica", "The Hobbit", "O Cortiço"]
    assert order("author")[0] == "Dom Casmurro"  # 'Assis, Machado de'
    assert order("pubdate") == ["Física Básica", "Dom Casmurro", "O Cortiço", "The Hobbit"]


def test_thumbnail_is_small_and_cached(make_library, tmp_path):
    pytest.importorskip("PIL")
    root = make_library(tmp_path / "lib")
    book = _by_title(database.load_library(root))["Dom Casmurro"]
    cache = tmp_path / "cache"
    first = thumbnails.thumbnail(book, root, cache)
    assert first[:3] == b"\xff\xd8\xff"
    assert len(list(cache.glob("*.jpg"))) == 1
    from PIL import Image
    import io
    assert max(Image.open(io.BytesIO(first)).size) <= max(thumbnails.THUMB_SIZE)
    assert thumbnails.thumbnail(book, root, cache) == first  # do cache


def test_thumbnail_never_raises(make_library, tmp_path, monkeypatch):
    root = make_library(tmp_path / "lib")
    book = _by_title(database.load_library(root))["Dom Casmurro"]
    book.cover_path(root).write_bytes(b"capa corrompida")
    assert thumbnails.thumbnail(book, root, tmp_path / "cache") is None
    monkeypatch.setitem(sys.modules, "PIL", None)  # sem Pillow: capa original
    assert thumbnails.thumbnail(book, root, None) == b"capa corrompida"


def test_year_for_books_before_1970(make_library, tmp_path):
    """No Windows astimezone() falha antes de 1970; o ano precisa sair mesmo assim."""
    books = _by_title(database.load_library(make_library(tmp_path / "lib")))
    assert books["O Cortiço"].year == 1890


def test_folder_uses_forward_slash_paths(tmp_path):
    book = database.LibraryBook(id=1, title="T", path="Autor/Título (1)")
    assert book.folder(tmp_path) == tmp_path / "Autor" / "Título (1)"
    assert book.format_path(tmp_path, "pdf") is None
    assert database.LibraryBook(id=2, title="S", series="X", series_index=2.5).series_text == "X [2.5]"


def test_sort_by_series_puts_volumes_in_order():
    books = [database.LibraryBook(id=1, title="OPM - Vol 18", series="One Punch Man", series_index=18),
             database.LibraryBook(id=2, title="Avulso"),
             database.LibraryBook(id=3, title="OPM - Vol 2", series="One Punch Man", series_index=2),
             database.LibraryBook(id=4, title="Berserk - Vol 1", series="Berserk", series_index=1)]
    assert [b.id for b in search.sort_books(books, "series")] == [4, 3, 1, 2]


def test_title_sort_keeps_volumes_in_order():
    books = [database.LibraryBook(id=n, title="One Punch Man", series="One Punch Man",
                             series_index=float(n)) for n in (18, 2, 1)]
    assert [b.series_index for b in search.sort_books(books, "title")] == [1, 2, 18]
