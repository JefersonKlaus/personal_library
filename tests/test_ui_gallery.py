"""Aba Galeria: grade de capas, busca, ordem, páginas e detalhes."""
import asyncio

from conftest import open_library


def test_shows_the_open_library_as_cover_grid(app, make_library, tmp_path):
    root = open_library(app, make_library, tmp_path)
    gallery = app.gallery
    assert gallery.body.controls == [gallery.grid] and len(gallery.grid.controls) == 4
    assert gallery.count_text.value == "4 livro(s)"
    assert "4 livro(s) em" in gallery.library_status.value
    assert gallery.library_field.value == str(root)
    assert gallery.view[0].title == "Física Básica"  # mais recentes primeiro


def test_search_and_sort(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    gallery.search_field.value = "cortico"
    asyncio.run(gallery.on_search(None))
    assert [b.title for b in gallery.view] == ["O Cortiço"]
    assert gallery.count_text.value == "1 de 4 livro(s)"
    gallery.search_field.value = "xyz"
    asyncio.run(gallery.on_search(None))
    assert gallery.body.controls == [gallery.empty_state]
    assert "Nenhum livro" in gallery.empty_text.value
    gallery.search_field.value = ""
    gallery.sort_dropdown.value = "title"
    asyncio.run(gallery.on_sort(None))
    assert gallery.view[0].title == "Dom Casmurro"
    assert app.settings.gallery_sort == "title"


def test_typed_folder_that_is_not_a_library(app, tmp_path):
    app.gallery.library_field.value = str(tmp_path)
    asyncio.run(app.gallery.on_reload(None))
    assert app.library is None
    assert app.gallery.body.controls == [app.gallery.empty_state]
    assert "não é uma biblioteca" in app.gallery.library_status.value


def test_details_dialog_opens_book(app, ui, make_library, tmp_path, monkeypatch):
    root = open_library(app, make_library, tmp_path)
    dom = next(b for b in app.books if b.title == "Dom Casmurro")
    rows = dict(ui.book_views.details_rows(dom))
    assert rows["Série"] == "Clássicos [1]" and rows["Publicado"] == "1899"
    assert rows["Identificadores"] == "isbn:9788535910667"
    app.gallery.show_details(dom, None)
    assert len(app.page.dialogs) == 1
    opened = []
    monkeypatch.setattr(ui.gallery_tab, "open_path", opened.append)
    app.page.dialogs[0].actions[1].on_click(None)  # Abrir livro
    assert opened == [dom.main_file(root)]
    app.page.dialogs[0].actions[2].on_click(None)  # Fechar
    assert app.page.dialogs == []


def test_pagination(app, ui, make_library, tmp_path, monkeypatch):
    monkeypatch.setattr(ui.gallery_tab, "GALLERY_PAGE_SIZE", 3)
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    assert len(gallery.grid.controls) == 3 and gallery.page_label.value == "Página 1 de 2"
    asyncio.run(gallery.on_next(None))
    assert len(gallery.grid.controls) == 1 and gallery.next_btn.disabled
