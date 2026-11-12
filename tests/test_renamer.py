import threading

import pytest

from personal_library import renamer
from personal_library.library.database import LibraryBook


class FakeCli:
    def __init__(self, fail_ids=()):
        self.calls = []
        self.fail_ids = set(fail_ids)

    def set_fields(self, library, book_id, fields):
        self.calls.append((book_id, dict(fields)))
        return (False, "biblioteca em uso") if book_id in self.fail_ids else (True, "")


def _series(name="Spider-gedon", titles=("Spider-gedon", "Spider-gedon", "Prólogo")):
    return [LibraryBook(id=n, title=title, series=name, series_index=float(n))
            for n, title in enumerate(titles, start=1)] + [LibraryBook(id=9, title="Outro")]


def test_title_goes_with_its_sort():
    """Só o título deixaria a ordenação antiga ('O Hobbit' ordenado como 'Hobbit, The')."""
    assert renamer.title_fields("O Hobbit") == {"title": "O Hobbit", "sort": "Hobbit, O"}


def test_rename_book(tmp_path):
    cli = FakeCli()
    book = LibraryBook(id=5, title="The Hobbit")
    assert renamer.rename_book(cli, tmp_path, book, "  O   Hobbit ") == (True, "")
    assert cli.calls == [(5, {"title": "O Hobbit", "sort": "Hobbit, O"})]
    assert renamer.rename_book(cli, tmp_path, book, "The Hobbit") == (True, "")  # igual: nada
    assert len(cli.calls) == 1
    with pytest.raises(renamer.RenameError, match="vazio"):
        renamer.rename_book(cli, tmp_path, book, "   ")


def test_titles_like_series():
    assert renamer.titles_like_series(_series(), "Spider-gedon") == 2
    assert renamer.titles_like_series(_series(), "Outra") == 0


def test_rename_series_only_touches_its_books(tmp_path):
    cli = FakeCli()
    report = renamer.rename_series(cli, tmp_path, _series(), "Spider-gedon", "Spider-Geddon")
    assert (report.total, report.done) == (3, 3)
    assert [book_id for book_id, _f in cli.calls] == [1, 2, 3]
    assert all(fields == {"series": "Spider-Geddon"} for _id, fields in cli.calls)


def test_rename_series_with_titles(tmp_path):
    cli = FakeCli()
    renamer.rename_series(cli, tmp_path, _series(), "Spider-gedon", "Spider-Geddon",
                          rename_titles=True)
    assert cli.calls[0][1] == {"series": "Spider-Geddon", "title": "Spider-Geddon",
                               "sort": "Spider-Geddon"}
    assert cli.calls[2][1] == {"series": "Spider-Geddon"}  # "Prólogo" tem título próprio


def test_rename_series_errors_cancel_and_progress(tmp_path):
    cli = FakeCli(fail_ids={2})
    seen = []
    report = renamer.rename_series(cli, tmp_path, _series(), "Spider-gedon", "X",
                                   progress=lambda d, t, m: seen.append((d, t)))
    assert (report.done, report.failed) == (2, 1)
    assert report.errors == ["Spider-gedon: biblioteca em uso"]
    assert seen == [(1, 3), (2, 3), (3, 3)]
    cancel = threading.Event()
    cancel.set()
    report = renamer.rename_series(FakeCli(), tmp_path, _series(), "Spider-gedon", "X",
                                   cancel=cancel)
    assert report.cancelled and report.done == 0
    with pytest.raises(renamer.RenameError):
        renamer.rename_series(FakeCli(), tmp_path, _series(), "Spider-gedon", " ")
