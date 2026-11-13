"""Reading a PDF one page at a time (Galeria > details > Abrir livro).

On the desktop the book opens in a reader window of its own (a separate process, see
test_reader_window.py). These tests use the reader inside the app window, which is what
the web version does (and the fallback when a window cannot be started); the reader
itself (pages, keys, buttons) is the same in both."""
import asyncio
from types import SimpleNamespace

from helpers import make_pdf, open_library


def _open(app, make_library, tmp_path, pages=5, title="Dom Casmurro"):
    """Opens the library, gives the book a real PDF and presses Abrir livro (web version:
    the reader opens inside the app window)."""
    app.page.web = True
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == title)
    make_pdf(book.main_file(root), pages=pages)
    app.gallery.show_details(book, None)
    asyncio.run(app.page.dialogs[-1].actions[0].on_click(None))  # Abrir livro
    return book


def _is_jpeg(data):
    return isinstance(data, bytes) and data[:3] == b"\xff\xd8\xff"


def _key(app, key):
    asyncio.run(app.on_page_key(SimpleNamespace(key=key, shift=False, ctrl=False,
                                                alt=False, meta=False)))


def test_open_book_shows_the_first_page_in_place_of_the_tabs(app, make_library, tmp_path):
    _open(app, make_library, tmp_path)
    reader = app.opener.reader
    assert reader is not None and app.page.dialogs == []  # the details window closed
    assert app.content.controls[1] is reader.control  # header and status bar stay
    assert reader.index == 0 and reader.page_field.value == "1"
    assert reader.count_text.value == "de 5"
    assert _is_jpeg(reader.image.src) and reader.image.visible and not reader.loading.visible
    assert reader.btn_prev.disabled and reader.btn_first.disabled
    assert not reader.btn_next.disabled


def test_buttons_turn_one_page_at_a_time(app, make_library, tmp_path):
    _open(app, make_library, tmp_path)
    reader = app.opener.reader
    first = reader.image.src
    asyncio.run(reader.on_next(None))
    assert reader.index == 1 and reader.page_field.value == "2"
    assert _is_jpeg(reader.image.src) and reader.image.src != first
    asyncio.run(reader.on_prev(None))
    assert reader.index == 0 and reader.image.src == first
    asyncio.run(reader.on_last(None))
    assert reader.index == 4 and reader.btn_next.disabled and reader.btn_last.disabled
    asyncio.run(reader.on_next(None))  # already on the last page
    assert reader.index == 4
    asyncio.run(reader.on_first(None))
    assert reader.index == 0


def test_typing_a_page_number(app, make_library, tmp_path):
    _open(app, make_library, tmp_path)
    reader = app.opener.reader
    reader.page_field.value = "4"
    asyncio.run(reader.on_page_submit(None))
    assert reader.index == 3
    reader.page_field.value = "99"  # past the end: the last page
    asyncio.run(reader.on_page_submit(None))
    assert reader.index == 4 and reader.page_field.value == "5"
    reader.page_field.value = "abc"  # not a number: stays, and the field is restored
    asyncio.run(reader.on_page_submit(None))
    assert reader.index == 4 and reader.page_field.value == "5"


def test_keyboard_turns_pages_and_esc_closes(app, make_library, tmp_path):
    _open(app, make_library, tmp_path)
    reader = app.opener.reader
    for key, index in [("Arrow Right", 1), ("Page Down", 2), (" ", 3), ("Arrow Left", 2),
                       ("Page Up", 1), ("End", 4), ("Home", 0), ("Arrow Down", 1),
                       ("Arrow Up", 0), ("A", 0)]:
        _key(app, key)
        assert reader.index == index, key
    reader.page_field.on_focus(None)  # typing a number: arrows belong to the field
    _key(app, "Arrow Right")
    assert reader.index == 0
    reader.page_field.on_blur(None)
    _key(app, "Escape")
    assert app.opener.reader is None and app.content.controls[1] is app.tabs


def test_back_button_returns_to_the_gallery_and_frees_the_pdf(app, make_library, tmp_path):
    _open(app, make_library, tmp_path)
    reader = app.opener.reader
    asyncio.run(reader.on_back(None))
    assert app.opener.reader is None and app.content.controls[1] is app.tabs
    assert reader.pages._closed
    assert len(app.gallery.cards) == 4  # the gallery is as it was


def test_open_externally_from_the_reader(app, ui, make_library, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(ui.book_opener, "open_with_system", opened.append)
    book = _open(app, make_library, tmp_path)
    toolbar = app.opener.reader.control.controls[0]
    toolbar.controls[-1].on_click(None)  # Abrir no programa padrão
    assert opened == [book.main_file(app.library)]


def test_a_stale_render_does_not_replace_a_newer_page(app, make_library, tmp_path,
                                                     monkeypatch):
    """Quick clicks: only the last page asked for ends up on screen, even when an
    earlier (slower) page finishes rendering after it."""
    import time

    _open(app, make_library, tmp_path)
    reader = app.opener.reader
    render = reader.pages.render

    def slow_page_4(index):
        if index == 3:
            time.sleep(0.3)  # page 4 finishes last
        return render(index)

    monkeypatch.setattr(reader.pages, "render", slow_page_4)

    async def two_quick_clicks():
        await asyncio.gather(reader.show(3), reader.show(1))

    asyncio.run(two_quick_clicks())
    assert reader.index == 1 and reader.image.src == render(1)


def test_a_page_that_fails_to_render_shows_a_message(app, make_library, tmp_path,
                                                    monkeypatch):
    _open(app, make_library, tmp_path)
    reader = app.opener.reader

    def broken(index):
        raise ValueError("página corrompida")

    monkeypatch.setattr(reader.pages, "render", broken)
    asyncio.run(reader.on_next(None))
    assert reader.message.visible and not reader.image.visible
    assert reader.message.value == "Não foi possível mostrar a página 2: página corrompida"
    assert reader.index == 1 and not reader.btn_prev.disabled  # can still move on
