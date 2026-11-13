"""Series sidebar of the gallery: filtering and renaming a series."""
import asyncio
import inspect

from helpers import log_lines, open_library, RecordingCli


def _rows(sidebar):
    """(name, count, has a rename button?) of each row of the sidebar."""
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
    # only real series have the (small) rename button
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
    assert [b.title for b in app.gallery.view] == ["Dom Casmurro", "O Cortiço"]  # in order
    assert app.gallery.sort_dropdown.value == "series"
    assert app.gallery.count_text.value == "2 de 4 livro(s)"
    asyncio.run(sidebar.list_view.controls[1].on_click(None))  # Sem série
    assert sorted(b.title for b in app.gallery.view) == ["Física Básica", "The Hobbit"]
    asyncio.run(sidebar.list_view.controls[0].on_click(None))  # Todos
    assert len(app.gallery.view) == 4


def test_rename_series_dialog_and_action(app, make_library, tmp_path, fake_cli):
    open_library(app, make_library, tmp_path)
    sidebar = app.gallery.sidebar
    asyncio.run(sidebar.list_view.controls[2].on_click(None))  # showing "Clássicos"
    cli = RecordingCli()
    fake_cli.set(cli)
    sidebar.list_view.controls[2].content.controls[-1].on_click(None)  # pencil
    dialog = app.page.dialogs[-1]
    field, titles, warning = dialog.content.controls[1:]
    assert field.value == "Clássicos" and not titles.visible  # no title equal to the series
    field.value = "clássicos"
    field.on_change(None)
    assert not warning.visible  # it is the series itself
    field.value = "Clássicos Brasileiros"
    field.on_change(None)
    asyncio.run(dialog.actions[-1].on_click(None))
    assert [fields for _id, fields in cli.calls] == [{"series": "Clássicos Brasileiros"}] * 2
    assert sidebar.selected is None  # the fixture does not change the database: the series 'nova' does not exist
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
