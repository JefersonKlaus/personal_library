"""The interface built with the REAL Flet controls (the other test_ui_* use a fake one).

The fake Flet accepts any argument, so a control argument that does not exist in the
installed Flet only showed up when the app ran: TextField(helper_text=...) crashed the
"Editar metadados" dialog (Flet 1.0 calls it `helper`). Building every screen and dialog
here with the real classes catches that kind of mistake. The page is still a fake one:
nothing is drawn, only the controls are created."""
import asyncio
import importlib
import sys

import pytest

from helpers import FakePage, open_library, press_shift
from src.core.settings import Settings


ft = pytest.importorskip("flet")


@pytest.fixture
def real_app(monkeypatch, tmp_path):
    for name in [name for name in sys.modules if name.startswith("src.ui.")]:
        monkeypatch.delitem(sys.modules, name)  # loaded again, now with the real Flet
    app_module = importlib.import_module("src.ui.app")
    assert app_module.ft is ft
    monkeypatch.setattr(app_module, "load_settings", lambda: Settings())
    monkeypatch.setattr(app_module, "save_settings", lambda _settings: True)
    monkeypatch.setattr(importlib.import_module("src.ui.library_picker"), "known_libraries",
                        lambda *a: [])
    monkeypatch.setattr(importlib.import_module("src.ui.book_opener"), "open_window",
                        lambda *args: None)  # no real reader window (separate process)
    app = app_module.PersonalLibraryApp(FakePage())
    app.gallery.thumb_cache = tmp_path / "thumbs"
    app.build()
    return app


def test_window_and_tabs(real_app):
    [root] = real_app.page.added
    assert isinstance(root, ft.Container) and isinstance(root.content, ft.KeyboardListener)


def test_gallery_cards_and_every_dialog(real_app, make_library, tmp_path):
    open_library(real_app, make_library, tmp_path)
    gallery, page = real_app.gallery, real_app.page
    assert len(gallery.cards) == 4
    card = gallery.cards[0]
    card.control.content.on_tap_down(None)

    gallery.show_details(card.book, None)  # details (double click / Abrir)
    assert isinstance(page.dialogs[-1], ft.AlertDialog)
    page.pop_dialog()

    for item in card.control.secondary_items:  # Abrir, Editar metadados
        item.on_click(None)
        assert isinstance(page.dialogs[-1], ft.AlertDialog)
        page.pop_dialog()

    gallery.click(gallery.cards[0].book.id)
    press_shift(real_app)
    gallery.click(gallery.cards[2].book.id)  # Shift+click: 3 books
    gallery.edit_metadata(gallery.cards[1].book, None)  # several books
    dialog = page.dialogs[-1]
    assert dialog.title.value == "Editar metadados de 3 livros"
    page.pop_dialog()

    sidebar = gallery.sidebar  # rename a series
    page.show_dialog(sidebar._rename_dialog("Clássicos"))
    assert isinstance(page.dialogs[-1], ft.AlertDialog)


def test_edit_dialog_validation_message(real_app, make_library, tmp_path):
    open_library(real_app, make_library, tmp_path)
    gallery = real_app.gallery
    gallery.edit_metadata(gallery.cards[0].book, None)
    editor = real_app.page.dialogs[-1].actions[-1].on_click.__self__
    editor.fields["year"].value = "ontem"
    asyncio.run(editor.save(None))
    assert editor.error.visible and "Ano inválido" in editor.error.value


def test_reader(real_app, make_library, tmp_path):
    from reportlab.pdfgen import canvas

    root = open_library(real_app, make_library, tmp_path)
    book = next(book for book in real_app.books if book.title == "Dom Casmurro")
    pdf = canvas.Canvas(str(book.main_file(root)))
    for number in (1, 2):
        pdf.drawString(72, 720, f"Página {number}")
        pdf.showPage()
    pdf.save()
    real_app.page.web = True  # the reader inside the app window (web version)
    asyncio.run(real_app.opener.open(book, book.main_file(root)))
    reader = real_app.opener.reader
    assert isinstance(reader.control, ft.Column) and isinstance(reader.image, ft.Image)
    assert reader.image.src[:3] == b"\xff\xd8\xff" and reader.count_text.value == "de 2"
    asyncio.run(reader.on_next(None))
    assert reader.index == 1
    asyncio.run(reader.on_back(None))
    assert real_app.opener.reader is None


def test_reader_window(real_app, tmp_path):
    from types import SimpleNamespace

    from reportlab.pdfgen import canvas

    reader_window = importlib.import_module("src.ui.reader_window")
    pdf_path = tmp_path / "livro.pdf"
    pdf = canvas.Canvas(str(pdf_path))
    pdf.drawString(72, 720, "Página 1")
    pdf.save()

    class Window(SimpleNamespace):
        async def close(self):
            self.closed = True

    page = FakePage()
    page.window = Window()
    asyncio.run(reader_window.reader_app(pdf_path, "Livro", 700, 880)(page))
    [control] = page.added
    assert isinstance(control, ft.Column)
    asyncio.run(page.on_keyboard_event(SimpleNamespace(key="Escape")))
    assert page.window.closed
