"""Aba Galeria: grade de capas, busca, ordem, páginas e detalhes."""
import asyncio
import inspect

from conftest import log_lines, open_library


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
    actions = app.page.dialogs[0].actions
    assert [button.value for button in actions] == ["Abrir livro", "Fechar"]  # sem "Abrir pasta"
    opened = []
    monkeypatch.setattr(ui.gallery_tab, "open_path", opened.append)
    actions[0].on_click(None)  # Abrir livro
    assert opened == [dom.main_file(root)]
    actions[1].on_click(None)  # Fechar
    assert app.page.dialogs == []


def _gestures(card):
    """O que o cartão faz com o mouse: (clique, duplo clique, botão direito > Abrir)."""
    detector = card.control.content
    [open_item] = card.control.secondary_items
    assert open_item.content == "Abrir"
    return detector.on_tap, detector.on_double_tap, open_item.on_click


def test_one_click_only_selects(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    first, second = gallery.cards[0], gallery.cards[1]
    assert not any(card.selected for card in gallery.cards)
    _gestures(first)[0](None)
    assert first.selected and gallery.selected_id == first.book.id
    assert app.page.dialogs == []  # um clique não abre nada
    _gestures(second)[0](None)
    assert second.selected and not first.selected  # só um selecionado por vez
    assert [card.selected for card in gallery.cards].count(True) == 1
    first.control.content.on_secondary_tap_down(None)  # botão direito também seleciona
    assert first.selected and not second.selected and app.page.dialogs == []


def test_double_click_or_right_click_open_opens_the_details(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    card = gallery.cards[2]
    _gestures(card)[1](None)  # dois cliques
    assert len(app.page.dialogs) == 1 and card.selected
    assert app.page.dialogs[0].title.controls[0].value == card.book.title
    app.page.pop_dialog()
    other = gallery.cards[0]
    _gestures(other)[2](None)  # botão direito > Abrir
    assert app.page.dialogs[0].title.controls[0].value == other.book.title
    assert other.selected and not card.selected


def test_selection_survives_search_and_sort(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    book_id = gallery.cards[1].book.id
    _gestures(gallery.cards[1])[0](None)
    gallery.sort_dropdown.value = "title"
    asyncio.run(gallery.on_sort(None))  # grade redesenhada
    assert [card.book.id for card in gallery.cards if card.selected] == [book_id]


def test_pagination(app, ui, make_library, tmp_path, monkeypatch):
    monkeypatch.setattr(ui.gallery_tab, "GALLERY_PAGE_SIZE", 3)
    open_library(app, make_library, tmp_path)
    gallery = app.gallery
    assert len(gallery.grid.controls) == 3 and gallery.page_label.value == "Página 1 de 2"
    asyncio.run(gallery.on_next(None))
    assert len(gallery.grid.controls) == 1 and gallery.next_btn.disabled


# ---------------------------------------------------------------- barra lateral de séries

class RecordingCli:
    def __init__(self, ok=True):
        self.calls, self.ok = [], ok

    def set_fields(self, library, book_id, fields):
        self.calls.append((book_id, fields))
        return (True, "") if self.ok else (False, "A biblioteca está sendo usada por outro programa.")


def _rows(sidebar):
    """(nome, quantidade, tem botão de renomear?) de cada linha da barra lateral."""
    rows = []
    for row in sidebar.list_view.controls:
        controls = row.content.controls
        name = next(c.value for c in controls if getattr(c, "expand", False))
        count = next(c.value for c in controls if getattr(c, "size", None) == 11)
        rows.append((name, count, any(getattr(c, "tooltip", "") == "Renomear série"
                                      for c in controls)))
    return rows


def test_sidebar_lists_all_no_series_and_each_series(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    # só séries de verdade têm o botão (pequeno) de renomear
    assert _rows(app.gallery.sidebar) == [("Todos os livros", "4", False),
                                          ("Sem série", "2", False), ("Clássicos", "2", True)]
    pencil = app.gallery.sidebar.list_view.controls[2].content.controls[-1]
    assert pencil.icon_size == 16


def test_choosing_a_series_filters_the_gallery(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    sidebar = app.gallery.sidebar
    classicos = sidebar.list_view.controls[2]
    assert inspect.iscoroutinefunction(classicos.on_click)
    asyncio.run(classicos.on_click(None))
    assert sidebar.selected == "Clássicos"
    assert [b.title for b in app.gallery.view] == ["Dom Casmurro", "O Cortiço"]  # em ordem
    assert app.gallery.sort_dropdown.value == "series"
    assert app.gallery.count_text.value == "2 de 4 livro(s)"
    asyncio.run(sidebar.list_view.controls[1].on_click(None))  # Sem série
    assert sorted(b.title for b in app.gallery.view) == ["Física Básica", "The Hobbit"]
    asyncio.run(sidebar.list_view.controls[0].on_click(None))  # Todos
    assert len(app.gallery.view) == 4


def test_rename_series_dialog_and_action(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    sidebar = app.gallery.sidebar
    asyncio.run(sidebar.list_view.controls[2].on_click(None))  # mostrando "Clássicos"
    cli = RecordingCli()
    fake_cli.set(cli)
    sidebar.list_view.controls[2].content.controls[-1].on_click(None)  # lápis
    dialog = app.page.dialogs[-1]
    field, titles, warning = dialog.content.controls[1:]
    assert field.value == "Clássicos" and not titles.visible  # nenhum título igual à série
    field.value = "clássicos"
    field.on_change(None)
    assert not warning.visible  # é ela mesma
    field.value = "Clássicos Brasileiros"
    field.on_change(None)
    asyncio.run(dialog.actions[-1].on_click(None))
    assert [fields for _id, fields in cli.calls] == [{"series": "Clássicos Brasileiros"}] * 2
    assert sidebar.selected is None  # a fixture não muda o banco: a série 'nova' não existe
    assert "renomeada para 'Clássicos Brasileiros': 2 de 2" in log_lines(app)[-1]


def test_rename_series_warns_when_name_exists(app, ui, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    books = app.books + [type(app.books[0])(id=50, title="X", series="Outra")]
    dialog = app.gallery.sidebar
    dialog.books = books
    built = dialog._rename_dialog("Clássicos")
    field, _titles, warning = built.content.controls[1:]
    field.value = "OUTRA"
    field.on_change(None)
    assert warning.visible and "Já existe a série 'Outra'" in warning.value


def test_rename_book_from_details(app, ui, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    hobbit = next(b for b in app.books if b.title == "The Hobbit")
    cli = RecordingCli()
    fake_cli.set(cli)
    app.gallery.show_details(hobbit, None)
    dialog = app.page.dialogs[-1]
    title_row = dialog.title
    edit = title_row.controls[1]
    assert edit.tooltip == "Renomear livro" and edit.icon_size == 16
    edit.on_click(None)
    field, save, cancel = title_row.controls
    assert field.value == "The Hobbit"
    cancel.on_click(None)
    assert title_row.controls[0].value == "The Hobbit"  # voltou sem mudar nada
    title_row.controls[1].on_click(None)
    field, save, _cancel = title_row.controls
    field.value = "O Hobbit"
    asyncio.run(save.on_click(None))
    assert cli.calls == [(hobbit.id, {"title": "O Hobbit", "sort": "Hobbit, O"})]
    assert title_row.controls[0].value == "O Hobbit"
    assert "Livro renomeado" in log_lines(app)[-1]


def test_rename_book_failure_keeps_editing(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    fake_cli.set(RecordingCli(ok=False))
    app.gallery.show_details(app.books[0], None)
    title_row = app.page.dialogs[-1].title
    title_row.controls[1].on_click(None)
    field, save, _cancel = title_row.controls
    field.value = "Novo"
    asyncio.run(save.on_click(None))
    assert title_row.controls[0] is field  # continua editando
    assert "sendo usada por outro programa" in log_lines(app)[-1]
    field.value = "   "
    asyncio.run(save.on_click(None))
    assert "não pode ficar vazio" in log_lines(app)[-1]
