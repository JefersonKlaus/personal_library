"""Editar metadados: one book, or several at once."""
import asyncio

from helpers import (gestures, log_lines, open_edit_dialog, open_library, press_ctrl, press_shift,
                     RecordingCli)


def test_edit_one_book_shows_every_field_and_writes_only_the_changes(
        app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    cli = RecordingCli()
    fake_cli.set(cli)
    card = next(card for card in app.gallery.cards if card.book.title == "Dom Casmurro")
    dialog = open_edit_dialog(app, card)
    fields = {key: field.value for key, field in dialog.fields.items()}
    assert fields["title"] == "Dom Casmurro" and fields["authors"] == "Machado de Assis"
    assert fields["series"] == "Clássicos" and fields["series_index"] == "1"
    assert fields["year"] == "1899" and fields["tags"] == "Brasil, Romance"
    assert fields["identifiers"] == "isbn:9788535910667"
    assert dialog.ticks == {}  # one book: no checkboxes, everything is saved
    dialog.fields["title"].value = "Dom Casmurro (edição revista)"
    dialog.fields["year"].value = "1900"
    asyncio.run(dialog.save(None))
    assert app.page.dialogs == []
    assert cli.calls == [(card.book.id, {
        "title": "Dom Casmurro (edição revista)", "sort": "Dom Casmurro (edição revista)",
        "pubdate": "1900-01-01T12:00:00+00:00"})]
    assert log_lines(app)[-1] == "Metadados gravados em 1 de 1 livro(s)."


def test_saving_without_changes_writes_nothing(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    cli = RecordingCli()
    fake_cli.set(cli)
    dialog = open_edit_dialog(app, app.gallery.cards[0])
    asyncio.run(dialog.save(None))
    assert cli.calls == []
    assert "1 já estavam assim" in log_lines(app)[-1]


def test_invalid_value_keeps_the_dialog_open(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    cli = RecordingCli()
    fake_cli.set(cli)
    dialog = open_edit_dialog(app, app.gallery.cards[0])
    dialog.fields["year"].value = "ontem"
    asyncio.run(dialog.save(None))
    assert dialog.error.visible and "Ano inválido" in dialog.error.value
    assert len(app.page.dialogs) == 1 and cli.calls == []  # fix it and save again
    dialog.fields["year"].value = "2001"
    asyncio.run(dialog.save(None))
    assert app.page.dialogs == [] and len(cli.calls) == 1


def test_edit_several_books_writes_only_the_ticked_fields(app, make_library, tmp_path,
                                                          fake_cli):
    open_library(app, make_library, tmp_path)
    cli = RecordingCli()
    fake_cli.set(cli)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[2])[0](None)
    press_shift(app, down=False)
    dialog = open_edit_dialog(app, gallery.cards[1])  # right button inside the selection
    assert dialog.dialog.title.value == "Editar metadados de 3 livros"
    assert "series_index" not in dialog.fields and "identifiers" not in dialog.fields
    assert dialog.fields["authors"].value == ""  # each book has its own author...
    assert dialog.fields["authors"].label == "Autor(es) (vários valores)"  # ...and it says so
    assert dialog.fields["title"].label == "Título (vários valores)"
    assert not any(tick.value for tick in dialog.ticks.values())
    dialog.fields["publisher"].value = "Editora Nova"
    dialog.fields["publisher"].on_change(None)  # typing ticks the field
    assert dialog.ticks["publisher"].value
    dialog.fields["tags"].value = "nunca gravado"  # changed, but not ticked
    asyncio.run(dialog.save(None))
    ids = [card.book.id for card in gallery.cards[:3]]
    assert cli.calls == [(book_id, {"publisher": "Editora Nova"}) for book_id in ids]
    assert log_lines(app)[-1] == "Metadados gravados em 3 de 3 livro(s)."


def test_several_books_need_a_ticked_field(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    press_ctrl(app)
    gestures(gallery.cards[0])[0](None)
    gestures(gallery.cards[3])[0](None)
    press_ctrl(app, down=False)
    dialog = open_edit_dialog(app, gallery.cards[3])
    asyncio.run(dialog.save(None))
    assert "Marque pelo menos um campo" in dialog.error.value and app.page.dialogs


def test_edit_on_a_book_outside_the_selection_edits_only_that_book(app, make_library,
                                                                   tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[1])[0](None)
    press_shift(app, down=False)
    dialog = open_edit_dialog(app, gallery.cards[3])
    assert [book.id for book in dialog.books] == [gallery.cards[3].book.id]
    assert gallery.selection.ids == {gallery.cards[3].book.id}


def test_books_hidden_by_the_search_are_not_edited(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gestures(gallery.cards[0])[0](None)
    press_shift(app)
    gestures(gallery.cards[3])[0](None)  # all 4 selected
    press_shift(app, down=False)
    gallery.search_field.value = "Clássicos"  # only the 2 books of the series
    asyncio.run(gallery.on_search(None))
    dialog = open_edit_dialog(app, gallery.cards[0])
    assert sorted(book.title for book in dialog.books) == ["Dom Casmurro", "O Cortiço"]


def test_edit_without_the_library_tool_says_so(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    fake_cli.set(None)
    dialog = open_edit_dialog(app, app.gallery.cards[0])
    dialog.fields["publisher"].value = "Nova"
    asyncio.run(dialog.save(None))
    assert "não encontrado: instale-o para alterar a biblioteca" in log_lines(app)[-1]
