"""Main window: building, log, jobs and the open library."""
import ast
import asyncio
from pathlib import Path

from helpers import open_library


def test_build_registers_picker_and_three_tabs(app):
    assert app.file_picker in app.page.services
    assert len(app.page.added) == 1
    assert app.tabs.length == 3
    tab_bar, tab_view = app.tabs.content.controls
    assert [tab.label for tab in tab_bar.tabs] == ["Importar", "Galeria", "Exportar"]
    assert len(tab_view.controls) == 3


def test_app_name(ui):
    from src import APP_NAME

    assert APP_NAME == "Personal Library"


def test_errors_show_in_status_bar_and_open_the_log(app):
    app.log("tudo certo")
    assert app.status_text.value == "tudo certo" and not app.log_panel.visible
    app.log("deu ruim", error=True)
    assert app.status_text.value == "deu ruim" and app.log_panel.visible
    app.on_toggle_log(None)
    assert not app.log_panel.visible


def test_cancel_sets_event(app):
    app.on_cancel(None)
    assert app.cancel_event.is_set()


def test_busy_disables_registered_actions(app):
    app.set_busy(True)
    assert app.import_tab.btn_scan.disabled and app.export_tab.btn_export.disabled
    assert app.library_picker.btn_create.disabled and app.btn_cancel.visible
    app.set_busy(False)
    assert not app.import_tab.btn_scan.disabled and not app.btn_cancel.visible


def test_open_library_is_shared_by_all_tabs(app, make_library, tmp_path):
    root = open_library(app, make_library, tmp_path)
    assert app.library == root and len(app.books) == 4
    assert app.settings.library == str(root)  # remembered for next time
    assert len(app.gallery.grid.controls) == 4
    assert len(app.export_tab.list_view.controls) == 4
    assert not app.library_picker.is_open


def test_open_invalid_or_empty_library(app, tmp_path):
    assert not asyncio.run(app.open_library(tmp_path))
    assert app.library is None and app.books == []
    assert app.library_picker.is_open
    assert not asyncio.run(app.open_library(""))
    assert app.settings.library == ""


def test_no_lambda_calls_an_async_method():
    """A lambda calling an async method returns a coroutine that Flet ignores
    (the button seems to do nothing). Async handlers have to be async def."""
    ui_dir = Path(__file__).parent.parent / "src" / "ui"
    trees = {path.name: ast.parse(path.read_text(encoding="utf-8"))
             for path in ui_dir.glob("*.py")}
    async_methods = {node.name for tree in trees.values() for node in ast.walk(tree)
                     if isinstance(node, ast.AsyncFunctionDef)}
    for name, tree in trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Lambda):
                for call in ast.walk(node.body):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                            and call.func.attr in async_methods:
                        raise AssertionError(f"{name}:{node.lineno} lambda chama "
                                             f"{call.func.attr} (async)")
