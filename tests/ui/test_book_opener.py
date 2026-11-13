"""Abrir livro on the desktop: the reader in a window of its own (a separate process),
so it can be maximized, minimized, resized or closed without blocking the app."""
import asyncio

from helpers import log_lines, make_pdf, open_library, press_open_book


def test_protected_or_broken_pdf_opens_in_the_default_program(app, ui, make_library,
                                                                tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(ui.book_opener, "open_with_system", opened.append)
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == "Dom Casmurro")
    book.main_file(root).write_bytes(b"%PDF-1.4 not really a pdf")
    app.gallery.show_details(book, None)
    asyncio.run(app.page.dialogs[-1].actions[0].on_click(None))
    assert app.opener.reader is None and opened == [book.main_file(root)]
    assert "não abre no app (o arquivo está danificado" in log_lines(app)[-1]


def test_other_formats_open_in_the_default_program(app, ui, make_library, tmp_path,
                                                   monkeypatch):
    opened = []
    monkeypatch.setattr(ui.book_opener, "open_with_system", opened.append)
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == "Dom Casmurro")
    epub = book.main_file(root).with_suffix(".epub")
    epub.write_bytes(b"epub")
    asyncio.run(app.opener.open(book, epub))
    assert app.opener.reader is None and opened == [epub]
    assert "Só PDFs abrem no app" in log_lines(app)[-1]


def test_missing_file_is_reported(app, make_library, tmp_path):
    root = open_library(app, make_library, tmp_path)
    book = app.books[0]
    asyncio.run(app.opener.open(book, root / "sumiu.pdf"))
    assert app.opener.reader is None and log_lines(app)[-1] == "Arquivo não encontrado na biblioteca."


# ---------------------------------------------------------------- the app side

def test_open_book_starts_a_reader_window_and_does_not_wait(app, ui, make_library,
                                                            tmp_path):
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == "Dom Casmurro")
    make_pdf(book.main_file(root), pages=3)
    app.page.window.height = 900
    press_open_book(app, book)
    assert ui.opened_windows == [(book.main_file(root), "Dom Casmurro", 900)]
    assert app.opener.reader is None and app.content.controls[1] is app.tabs  # app untouched
    assert app.page.dialogs == []  # the details window closed
    assert log_lines(app)[-1] == "'Dom Casmurro' aberto em uma janela de leitura."


def test_several_books_open_in_several_windows(app, ui, make_library, tmp_path):
    root = open_library(app, make_library, tmp_path)
    for book in app.books[:2]:
        make_pdf(book.main_file(root), pages=3)
        press_open_book(app, book)
    assert [title for _path, title, _height in ui.opened_windows] == \
        [book.title for book in app.books[:2]]


def test_a_pdf_that_cannot_be_read_opens_no_window(app, ui, make_library, tmp_path,
                                                   monkeypatch):
    opened = []
    monkeypatch.setattr(ui.book_opener, "open_with_system", opened.append)
    root = open_library(app, make_library, tmp_path)
    book = app.books[0]  # the sample library has placeholder files, not real PDFs
    press_open_book(app, book)
    assert ui.opened_windows == [] and opened == [book.main_file(root)]
    assert "não abre no app (o arquivo está danificado" in log_lines(app)[-1]


def test_when_no_window_can_be_started_the_book_opens_in_the_app(app, ui, make_library,
                                                                tmp_path, monkeypatch):
    def cannot(*_args):
        raise OSError("o app empacotado não abre janelas extras")

    monkeypatch.setattr(ui.book_opener, "open_window", cannot)
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == "Dom Casmurro")
    make_pdf(book.main_file(root), pages=3)
    press_open_book(app, book)
    assert app.opener.reader is not None and app.content.controls[1] is app.opener.reader.control
    assert "Não foi possível abrir uma janela de leitura (o app empacotado" in \
        log_lines(app)[-1]


def test_web_version_reads_inside_the_app(app, ui, make_library, tmp_path):
    """A browser tab cannot open desktop windows: the reader takes the place of the tabs."""
    app.page.web = True
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == "Dom Casmurro")
    make_pdf(book.main_file(root), pages=3)
    press_open_book(app, book)
    assert ui.opened_windows == [] and app.opener.reader is not None


# ---------------------------------------------------------------- a window that fails

class _Process:
    def __init__(self, codes):
        self.codes = list(codes)  # what poll() returns, call after call
        self.returncode = None

    def poll(self):
        self.returncode = self.codes.pop(0) if self.codes else self.returncode
        return self.returncode


def test_a_reader_window_that_fails_says_so(app, ui):
    asyncio.run(app.opener.watch(_Process([None, 1]), "Dom Casmurro"))
    assert "A janela de leitura de 'Dom Casmurro' não abriu (erro 1)" in log_lines(app)[-1]
    assert "reader-errors.log" in log_lines(app)[-1]


def test_a_reader_window_that_opens_or_is_closed_says_nothing(app, ui):
    before = list(log_lines(app))
    asyncio.run(app.opener.watch(_Process([None, None, 0]), "A"))  # closed: fine
    asyncio.run(app.opener.watch(_Process([None] * 100), "B", seconds=0.5))  # open
    assert log_lines(app) == before


def test_open_book_watches_the_new_window(app, ui, make_library, tmp_path, monkeypatch):
    process = _Process([None])
    monkeypatch.setattr(ui.book_opener, "open_window", lambda *args: process)
    root = open_library(app, make_library, tmp_path)
    book = next(book for book in app.books if book.title == "Dom Casmurro")
    make_pdf(book.main_file(root), pages=3)
    press_open_book(app, book)
    assert (app.opener.watch, (process, "Dom Casmurro")) in app.page.tasks
