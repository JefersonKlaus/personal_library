"""The reader window program (what runs in the separate process)."""
import asyncio
from types import SimpleNamespace

from helpers import FakePage, make_pdf


# ---------------------------------------------------------------- the reader window

class _Window(SimpleNamespace):
    closed = False

    async def close(self):
        self.closed = True


def _window_page():
    page = FakePage()
    page.window = _Window()
    return page


def test_the_reader_window_shows_the_book(ui, tmp_path):
    page = _window_page()
    pdf = make_pdf(tmp_path / "livro.pdf", pages=3)
    asyncio.run(ui.reader_window.reader_app(pdf, "Dom Casmurro", 700, 880)(page))
    assert page.title == "Dom Casmurro"
    assert (page.window.width, page.window.height) == (700, 880)
    assert (page.window.min_width, page.window.min_height) == (420, 480)
    [control] = page.added
    toolbar = control.controls[0]
    assert not any(getattr(item, "tooltip", "").startswith("Voltar") for item in
                   toolbar.controls)  # no "back to the gallery": the window has its X
    key = page.on_keyboard_event
    asyncio.run(key(SimpleNamespace(key="Arrow Right")))
    reader = key.__self__
    assert reader.index == 1 and reader.image.src[:3] == b"\xff\xd8\xff"
    asyncio.run(key(SimpleNamespace(key="Escape")))  # Esc closes the window
    assert page.window.closed


def test_the_reader_window_explains_a_pdf_that_changed(ui, tmp_path):
    page = _window_page()
    broken = tmp_path / "livro.pdf"
    broken.write_bytes(b"%PDF-1.4 broken")
    asyncio.run(ui.reader_window.reader_app(broken, "Livro")(page))
    [message] = page.added
    assert "Não foi possível abrir livro.pdf: o arquivo está danificado" in message.value
