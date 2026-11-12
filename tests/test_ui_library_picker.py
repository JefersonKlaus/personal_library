"""Escolha da biblioteca: aviso, bibliotecas conhecidas, escolher, criar e trocar."""
import asyncio
import inspect

from conftest import FakePicker, log_lines

from personal_library.library.manager import DATABASE_FILE, DEFAULT_LIBRARY_NAME


def test_asks_for_a_library_when_there_is_none(app):
    picker = app.library_picker
    assert picker.is_open and not picker.current_row.visible
    assert picker.title.value == "Nenhuma biblioteca escolhida ainda."
    assert app.import_tab.btn_import.disabled
    app.settings.library = "/caminho/que/sumiu"
    picker.refresh()
    assert "não foi encontrada" in picker.title.value


def test_not_a_library_message(app, tmp_path):
    app.settings.library = str(tmp_path)
    app.library_picker.refresh()
    assert f"falta o {DATABASE_FILE}" in app.library_picker.title.value


def test_use_a_known_library(app, ui, make_library, tmp_path, monkeypatch):
    root = make_library(tmp_path / DEFAULT_LIBRARY_NAME)
    monkeypatch.setattr(ui.library_picker, "known_libraries", lambda *a: [root])
    app.library_picker.refresh()
    use = app.library_picker.suggestions.controls[1].controls[-1]
    assert inspect.iscoroutinefunction(use.on_click)
    asyncio.run(use.on_click(None))
    assert app.library == root and app.settings.library == str(root)
    assert not app.library_picker.is_open and app.library_picker.current_row.visible
    assert str(root) in app.library_picker.current_text.value


def test_choose_existing_library_accepts_parent_folder(app, make_library, tmp_path):
    root = make_library(tmp_path / "Documentos" / DEFAULT_LIBRARY_NAME)
    app.file_picker = FakePicker(folder=str(tmp_path / "Documentos"))
    asyncio.run(app.library_picker.on_choose(None))
    assert app.library == root
    app.file_picker = FakePicker(folder=str(tmp_path / "vazia"))
    asyncio.run(app.library_picker.on_choose(None))
    assert any("não é uma biblioteca" in line for line in log_lines(app))
    assert app.library == root  # continua a anterior


def test_switch_and_cancel(app, make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    asyncio.run(app.library_picker.use(root))
    app.library_picker.on_switch(None)
    assert app.library_picker.is_open and app.library_picker.btn_cancel.visible
    assert app.library_picker.title.value == f"Trocar de biblioteca (atual: {root})"
    app.library_picker.on_cancel(None)
    assert not app.library_picker.is_open


def test_create_new_library(app, make_library, tmp_path, fake_cli):
    fake_cli.set(None)
    asyncio.run(app.library_picker.on_create(None))
    assert any("instalado" in line for line in log_lines(app))

    created = []

    def create_library(target):
        make_library(target, books=[])
        created.append(target)
        return True, ""

    fake_cli.set(type("Cli", (), {"create_library": staticmethod(create_library)})())
    busy = tmp_path / "Documentos"
    busy.mkdir()
    (busy / "foto.jpg").write_bytes(b"x")
    app.file_picker = FakePicker(folder=str(busy))
    asyncio.run(app.library_picker.on_create(None))
    dialog = app.page.dialogs[-1]
    assert str(busy / DEFAULT_LIBRARY_NAME) in [c.value for c in dialog.content.controls]
    create_button = dialog.actions[-1]
    assert inspect.iscoroutinefunction(create_button.on_click)
    asyncio.run(create_button.on_click(None))
    assert created == [busy / DEFAULT_LIBRARY_NAME]
    assert app.library == busy / DEFAULT_LIBRARY_NAME and not app.library_picker.is_open
    assert "Alternar/criar biblioteca" in log_lines(app)[-1]


def test_create_library_failure_is_reported(app, tmp_path):
    failing = type("Cli", (), {"create_library": staticmethod(
        lambda target: (False, "Feche o programa e tente de novo."))})()
    asyncio.run(app.library_picker.create_at(tmp_path / "nova", failing))
    assert "Feche o programa" in log_lines(app)[-1]
    assert app.library is None
