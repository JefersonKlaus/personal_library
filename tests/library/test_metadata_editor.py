"""Editing metadata: text of the dialog -> fields of the library tool, and the writing."""
import threading
from datetime import datetime

import pytest

from helpers import RecordingCli
from src.library import metadata_editor as editor
from src.library.database import LibraryBook
from src.library.metadata_editor import MetadataError


def _book(**changes):
    values = dict(id=1, title="Dom Casmurro", authors=["Machado de Assis"],
                  series="Clássicos", series_index=1.0, publisher="Garnier",
                  pubdate=datetime.fromisoformat("1899-06-15 12:00:00+00:00"),
                  tags=["Brasil", "Romance"], languages=["por"],
                  identifiers={"isbn": "9788535910667"},
                  comments="<p>Um <b>clássico</b> da literatura.</p>")
    values.update(changes)
    return LibraryBook(**values)


def _as_typed(book):
    """Every field exactly as the one-book dialog shows it."""
    return {key: editor.current_text(book, key) for key in editor.FIELDS}


# ---------------------------------------------------------------- text -> library fields

def test_title_and_authors_carry_their_sort_names():
    assert editor.library_fields("title", "  O   Hobbit ") == {"title": "O Hobbit",
                                                              "sort": "Hobbit, O"}
    assert editor.library_fields("authors", "Ana Lima & Rui Dias & ana lima") == {
        "authors": "Ana Lima & Rui Dias", "author_sort": "Lima, Ana & Dias, Rui"}
    assert editor.library_fields("authors", " ")["authors"] == "Unknown"


def test_empty_title_is_refused():
    with pytest.raises(MetadataError, match="título"):
        editor.library_fields("title", "   ")


def test_year_goes_at_noon_utc_and_empty_clears_it():
    assert editor.library_fields("year", "2012") == {"pubdate": "2012-01-01T12:00:00+00:00"}
    assert editor.library_fields("year", "") == {"pubdate": editor.UNDEFINED_DATE}
    for wrong in ("12", "20x2", "12345", "-1999"):
        with pytest.raises(MetadataError, match="Ano inválido"):
            editor.library_fields("year", wrong)


def test_volume_accepts_comma_and_defaults_to_one():
    assert editor.library_fields("series_index", "2,5") == {"series_index": "2.5"}
    assert editor.library_fields("series_index", "03") == {"series_index": "3"}
    assert editor.library_fields("series_index", "") == {"series_index": "1"}
    for wrong in ("dois", "-1"):
        with pytest.raises(MetadataError, match="Volume inválido"):
            editor.library_fields("series_index", wrong)


def test_tags_languages_and_identifiers():
    assert editor.library_fields("tags", "romance, Brasil,, romance ") == {
        "tags": "Brasil,romance"}
    assert editor.library_fields("languages", "pt, en, por") == {"languages": "por,eng"}
    with pytest.raises(MetadataError, match="Idioma inválido"):
        editor.library_fields("languages", "português")
    assert editor.library_fields("identifiers", "ISBN: 978-85 , doi:10.1/x:y") == {
        "identifiers": "doi:10.1/x:y,isbn:978-85"}
    assert editor.library_fields("identifiers", "") == {"identifiers": ""}
    with pytest.raises(MetadataError, match="Identificador inválido"):
        editor.library_fields("identifiers", "9788535910667")


def test_description_is_saved_as_escaped_paragraphs():
    assert editor.library_fields("comments", "Linha 1\nlinha 2\n\n<b>2º</b> & fim") == {
        "comments": "<p>Linha 1<br>linha 2</p><p>&lt;b&gt;2º&lt;/b&gt; &amp; fim</p>"}
    assert editor.library_fields("comments", "  ") == {"comments": ""}


# ---------------------------------------------------------------- what changes

def test_nothing_changes_when_the_dialog_is_saved_as_it_opened():
    """Round trip: the HTML description, the exact date and the author sort name adjusted
    in the library program all survive a save without edits."""
    book = _book(author_sort="Assis, Machado (ajustado)")
    assert editor.changes_for(book, _as_typed(book)) == {}


def test_only_the_changed_fields_are_written():
    book = _book()
    values = _as_typed(book)
    values.update(year="1900", tags="Romance, Brasil, Clássico")
    assert editor.changes_for(book, values) == {
        "pubdate": "1900-01-01T12:00:00+00:00", "tags": "Brasil,Clássico,Romance"}


def test_typing_the_same_thing_differently_is_not_a_change():
    book = _book()
    assert editor.changes_for(book, {"tags": "romance,brasil"}) == {"tags": "brasil,romance"}
    assert editor.changes_for(book, {"tags": "Romance ,Brasil", "languages": "pt",
                                     "authors": "Machado  de Assis"}) == {}


def test_series_goes_before_its_volume():
    book = _book(series="", series_index=1.0)
    fields = editor.changes_for(book, {"series_index": "4", "series": "Nova"})
    assert list(fields) == ["series", "series_index"]


def test_common_text_of_several_books():
    books = [_book(id=1), _book(id=2, authors=["Outro Autor"])]
    assert editor.common_text(books, "series") == "Clássicos"
    assert editor.common_text(books, "authors") is None


def test_validate_checks_everything_before_writing():
    with pytest.raises(MetadataError, match="pelo menos um campo"):
        editor.validate({}, 1)
    with pytest.raises(MetadataError, match="Volume e Identificadores"):
        editor.validate({"series_index": "2", "identifiers": "isbn:1"}, 2)
    editor.validate({"series_index": "2", "identifiers": "isbn:1"}, 1)  # one book: fine


# ---------------------------------------------------------------- writing

def test_apply_changes_to_several_books(tmp_path):
    books = [_book(id=1), _book(id=2, publisher="Outra"), _book(id=3)]  # 2: already "Outra"
    cli, progress = RecordingCli(fail_ids={3}), []
    report = editor.apply_changes(cli, tmp_path, books, {"publisher": "Outra"},
                                  progress=lambda *args: progress.append(args))
    assert cli.calls == [(1, {"publisher": "Outra"}), (3, {"publisher": "Outra"})]
    assert (report.total, report.done, report.unchanged, report.failed) == (3, 1, 1, 1)
    assert report.errors == ["Dom Casmurro: biblioteca em uso"]
    assert [done for done, _total, _title in progress] == [1, 2, 3]
    assert report.summary() == ("Metadados gravados em 1 de 3 livro(s); 1 já estavam "
                                "assim; 1 com erro.")


def test_invalid_value_writes_nothing(tmp_path):
    cli = RecordingCli()
    with pytest.raises(MetadataError):
        editor.apply_changes(cli, tmp_path, [_book(id=1), _book(id=2)],
                             {"publisher": "Nova", "year": "ontem"})
    assert cli.calls == []


def test_cancel_stops_between_books(tmp_path):
    cancel, cli = threading.Event(), RecordingCli()
    calls = []

    def progress(done, _total, _title):
        calls.append(done)
        cancel.set()  # the user cancels while the first book is written

    report = editor.apply_changes(cli, tmp_path, [_book(id=1), _book(id=2)],
                                  {"publisher": "Nova"}, progress=progress, cancel=cancel)
    assert report.cancelled and report.done == 1 and len(cli.calls) == 1
    assert report.summary().endswith("(cancelado).")
