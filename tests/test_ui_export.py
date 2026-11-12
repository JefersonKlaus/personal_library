"""Aba Exportar: seleção de livros, destino e as ações."""
import asyncio

from conftest import FakePicker, log_lines, open_library


def test_empty_without_library(app):
    assert app.export_tab.body.controls == [app.export_tab.empty]


def test_options_read_controls(app):
    tab = app.export_tab
    tab.cb_folder.value, tab.cb_cover.value = False, False
    options = tab.options(dry_run=True)
    assert (options.folder_per_book, options.include_cover, options.dry_run) == (False, False,
                                                                                 True)


def test_lists_library_books_all_selected(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    tab = app.export_tab
    assert tab.body.controls == [tab.list_view] and len(tab.list_view.controls) == 4
    assert tab.summary.value == "4 de 4 livro(s) marcados para exportar"


def test_filter_and_select_all(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    tab = app.export_tab
    tab.search_field.value = "clássicos"
    tab.on_search(None)
    assert len(tab.list_view.controls) == 2
    tab.select_all(False)  # só os do filtro
    assert len(tab.selected) == 2 and "2 no filtro" in tab.summary.value
    tab.select_all(True)
    assert len(tab.selected) == 4


def test_dry_run_then_real_then_undo(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    tab = app.export_tab
    hobbit = next(b for b in app.books if b.title == "The Hobbit")
    tab.toggle(hobbit, False)
    dest = tmp_path / "pendrive"
    tab.dest_field.value = str(dest)
    asyncio.run(tab.on_dry_run(None))
    assert not dest.exists() and tab.results[1][1].startswith("iria para")
    asyncio.run(tab.on_export(None))
    pdfs = sorted(p.name for p in dest.rglob("*.pdf"))
    assert len(pdfs) == 3 and "The Hobbit - J. R. R. Tolkien.pdf" not in pdfs
    assert len(list(dest.rglob("*.opf"))) == 3
    assert log_lines(app)[-1] == f"3 livro(s) exportados para {dest}."
    assert "3 exportado(s)" in tab.summary.value
    asyncio.run(tab.on_undo(None))
    assert not list(dest.rglob("*.pdf")) and tab.results == {}


def test_requires_library_selection_and_destination(app, make_library, tmp_path):
    tab = app.export_tab
    asyncio.run(tab.on_export(None))
    assert any("Escolha a biblioteca" in line for line in log_lines(app))
    open_library(app, make_library, tmp_path)
    tab.select_all(False)
    asyncio.run(tab.on_export(None))
    assert any("Marque ao menos" in line for line in log_lines(app))
    tab.select_all(True)
    tab.dest_field.value = ""
    asyncio.run(tab.on_export(None))
    assert any("pasta de destino" in line for line in log_lines(app))


def test_refuses_destination_inside_a_library(app, make_library, tmp_path):
    root = open_library(app, make_library, tmp_path)
    app.export_tab.dest_field.value = str(root / "copia")
    asyncio.run(app.export_tab.on_export(None))
    assert any("dentro de uma biblioteca" in line for line in log_lines(app))


def test_reloading_keeps_selection_and_selects_new_books(app, make_library, tmp_path):
    open_library(app, make_library, tmp_path)
    tab = app.export_tab
    tab.selected.discard(1)
    new_book = type(app.books[0])(id=99, title="Novo")
    app.books = app.books + [new_book]
    tab.on_library_changed(changed=False)
    assert 1 not in tab.selected and 99 in tab.selected
    tab.on_library_changed(changed=True)  # outra biblioteca: tudo marcado
    assert tab.selected == {b.id for b in app.books}


def test_undo_without_manifest(app, tmp_path):
    app.export_tab.dest_field.value = str(tmp_path)
    asyncio.run(app.export_tab.on_undo(None))
    assert any("Não há exportação" in line for line in log_lines(app))


def test_pick_destination_sets_field(app, tmp_path):
    app.file_picker = FakePicker(folder=str(tmp_path))
    asyncio.run(app.export_tab.on_pick_destination(None))
    assert app.export_tab.dest_field.value == str(tmp_path)
