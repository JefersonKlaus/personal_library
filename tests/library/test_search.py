"""Search, order and series of the library books."""
from src.library import database, search


def test_search_ignores_case_and_accents(make_library, tmp_path):
    books = database.load_library(make_library(tmp_path / "lib"))
    titles = lambda query: sorted(b.title for b in search.search(books, query))  # noqa: E731
    assert titles("cortico") == ["O Cortiço"]
    assert titles("MACHADO") == ["Dom Casmurro"]
    assert titles("romance brasil") == ["Dom Casmurro"]  # every word
    assert titles("clássicos") == ["Dom Casmurro", "O Cortiço"]  # series
    assert titles("garnier") == ["Dom Casmurro"]  # publisher
    assert titles("  ") == sorted(b.title for b in books)
    assert titles("nada disso") == []


def test_sort_orders(make_library, tmp_path):
    books = database.load_library(make_library(tmp_path / "lib"))
    order = lambda key: [b.title for b in search.sort_books(books, key)]  # noqa: E731
    assert order("added") == ["Física Básica", "O Cortiço", "The Hobbit", "Dom Casmurro"]
    assert order("title") == ["Dom Casmurro", "Física Básica", "The Hobbit", "O Cortiço"]
    assert order("author")[0] == "Dom Casmurro"  # 'Assis, Machado de'
    assert order("pubdate") == ["Física Básica", "Dom Casmurro", "O Cortiço", "The Hobbit"]


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


def test_series_counts_and_filter():
    books = [database.LibraryBook(id=1, title="A", series="Zeta"),
             database.LibraryBook(id=2, title="B", series="álbum"),
             database.LibraryBook(id=3, title="C", series="Zeta"),
             database.LibraryBook(id=4, title="D")]
    assert search.series_counts(books) == [("álbum", 1), ("Zeta", 2)]  # accent-insensitive order
    assert [b.id for b in search.in_series(books, "Zeta")] == [1, 3]
    assert [b.id for b in search.in_series(books, search.NO_SERIES)] == [4]
    assert len(search.in_series(books, None)) == 4
