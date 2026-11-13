"""Helpers shared by the tests: test files, a sample library, a fake Flet, a fake library
tool and the gestures of the gallery. The fixtures that use them are in conftest.py."""
from __future__ import annotations

import asyncio
import types
from pathlib import Path
from types import SimpleNamespace

from src.library.manager import DATABASE_FILE


# ---------------------------------------------------------------- files

def make_pdf(path: Path, title: str | None = None, author: str | None = None,
             text: str = "conteudo", pages: int = 1, landscape: bool = False) -> Path:
    """A real PDF generated on the fly (A4). With several pages each one says its number,
    so the pages look different."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.pagesizes import landscape as turned
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=turned(A4) if landscape else A4)
    if title is not None:
        pdf.setTitle(title)
    if author is not None:
        pdf.setAuthor(author)
    for number in range(1, pages + 1):
        pdf.drawString(72, 720, text if pages == 1 else f"{text} - página {number}")
        pdf.showPage()
    pdf.save()
    return path


# ---------------------------------------------------------------- library

# Subset of the real schema of the library database, with the same table names.
LIBRARY_SCHEMA = """
CREATE TABLE books (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL DEFAULT 'Unknown'
    COLLATE NOCASE, sort TEXT COLLATE NOCASE, timestamp TIMESTAMP, pubdate TIMESTAMP,
    series_index REAL NOT NULL DEFAULT 1.0, author_sort TEXT COLLATE NOCASE,
    path TEXT NOT NULL DEFAULT '', uuid TEXT, has_cover BOOL DEFAULT 0);
CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE,
    sort TEXT COLLATE NOCASE);
CREATE TABLE books_authors_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL,
    author INTEGER NOT NULL);
CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE);
CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, tag INTEGER NOT NULL);
CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE, sort TEXT);
CREATE TABLE books_series_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL,
    series INTEGER NOT NULL);
CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE, sort TEXT);
CREATE TABLE books_publishers_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL,
    publisher INTEGER NOT NULL);
CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT NOT NULL COLLATE NOCASE);
CREATE TABLE books_languages_link (id INTEGER PRIMARY KEY, book INTEGER NOT NULL,
    lang_code INTEGER NOT NULL, item_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE data (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, format TEXT NOT NULL,
    uncompressed_size INTEGER NOT NULL, name TEXT NOT NULL);
CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER NOT NULL,
    type TEXT NOT NULL DEFAULT 'isbn', val TEXT NOT NULL);
CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER NOT NULL, text TEXT NOT NULL);
"""

SAMPLE_BOOKS = [
    # title, authors, sort, author_sort, added, published, series, tags, cover
    ("Dom Casmurro", ["Machado de Assis"], "Dom Casmurro", "Assis, Machado de",
     "2024-01-10 10:00:00+00:00", "1899-06-15 12:00:00+00:00", ("Clássicos", 1.0),
     ["Romance", "Brasil"], True),
    ("O Cortiço", ["Aluísio Azevedo"], "O Cortiço", "Azevedo, Aluísio",
     "2024-03-01 10:00:00+00:00", "1890-06-15 12:00:00+00:00", ("Clássicos", 2.0),
     ["Romance"], True),
    ("The Hobbit", ["J. R. R. Tolkien"], "Hobbit, The", "Tolkien, J. R. R.",
     "2024-02-01 10:00:00+00:00", "0101-01-01 00:00:00+00:00", None, ["Fantasia"], False),
    ("Física Básica", ["Ana Lima", "Rui Dias"], "Física Básica", "Lima, Ana & Dias, Rui",
     "2024-04-01 10:00:00+00:00", "2019-06-15 12:00:00+00:00", None, [], True),
]


def _jpeg(path: Path, color: str = "navy") -> None:
    from PIL import Image

    Image.new("RGB", (600, 900), color).save(path, "JPEG")


def make_library_at(root: Path, books=SAMPLE_BOOKS) -> Path:
    """Creates a library: database + Author/Title (id)/."""
    import sqlite3

    root.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(root / DATABASE_FILE)
    conn.executescript(LIBRARY_SCHEMA)
    for book_id, (title, authors, sort, a_sort, added, pub, series, tags, cover) in enumerate(
            books, start=1):
        rel = f"{authors[0]}/{title} ({book_id})"
        folder = root.joinpath(*rel.split("/"))
        folder.mkdir(parents=True)
        name = f"{title} - {authors[0]}"
        (folder / f"{name}.pdf").write_bytes(b"%PDF-1.4 livro")
        if cover:
            _jpeg(folder / "cover.jpg")
        conn.execute("INSERT INTO books (id, title, sort, author_sort, timestamp, pubdate, path, "
                     "has_cover, series_index) VALUES (?,?,?,?,?,?,?,?,?)",
                     (book_id, title, sort, a_sort, added, pub, rel, int(cover),
                      series[1] if series else 1.0))
        for name_ in authors:
            row = conn.execute("SELECT id FROM authors WHERE name=?", (name_,)).fetchone()
            author_id = row[0] if row else conn.execute(
                "INSERT INTO authors (name) VALUES (?)", (name_,)).lastrowid
            conn.execute("INSERT INTO books_authors_link (book, author) VALUES (?,?)",
                         (book_id, author_id))
        for tag in tags:
            row = conn.execute("SELECT id FROM tags WHERE name=?", (tag,)).fetchone()
            tag_id = row[0] if row else conn.execute(
                "INSERT INTO tags (name) VALUES (?)", (tag,)).lastrowid
            conn.execute("INSERT INTO books_tags_link (book, tag) VALUES (?,?)", (book_id, tag_id))
        if series:
            row = conn.execute("SELECT id FROM series WHERE name=?", (series[0],)).fetchone()
            series_id = row[0] if row else conn.execute(
                "INSERT INTO series (name) VALUES (?)", (series[0],)).lastrowid
            conn.execute("INSERT INTO books_series_link (book, series) VALUES (?,?)",
                         (book_id, series_id))
        conn.execute("INSERT INTO data (book, format, uncompressed_size, name) VALUES (?,?,?,?)",
                     (book_id, "PDF", 14, name))
    por = conn.execute("INSERT INTO languages (lang_code) VALUES ('por')").lastrowid
    eng = conn.execute("INSERT INTO languages (lang_code) VALUES ('eng')").lastrowid
    conn.execute("INSERT INTO books_languages_link (book, lang_code, item_order) VALUES (1,?,0)",
                 (por,))
    conn.execute("INSERT INTO books_languages_link (book, lang_code, item_order) VALUES (1,?,1)",
                 (eng,))
    pub = conn.execute("INSERT INTO publishers (name) VALUES ('Garnier')").lastrowid
    conn.execute("INSERT INTO books_publishers_link (book, publisher) VALUES (1,?)", (pub,))
    conn.execute("INSERT INTO identifiers (book, type, val) VALUES (1,'isbn','9788535910667')")
    conn.execute("INSERT INTO comments (book, text) VALUES (1, ?)",
                 ("<p>Narrado por <b>Bento</b>.</p><p>Fim &amp; tal.</p>",))
    conn.commit()
    conn.close()
    return root


class RecordingCli:
    """The library tool, recording what it was asked to change; the books in `fail_ids`
    fail with `error`."""

    def __init__(self, fail_ids=(), error="biblioteca em uso"):
        self.calls, self.fail_ids, self.error = [], set(fail_ids), error

    def set_fields(self, library, book_id, fields):
        self.calls.append((book_id, dict(fields)))
        return (False, self.error) if book_id in self.fail_ids else (True, "")


# ---------------------------------------------------------------- interface (fake Flet)
#
# Checks the wiring logic of the interface (buttons -> functions, state, messages), NOT the
# looks nor the real Flet API (test_real_flet.py builds the screens with the real one).

UI_MODULES = ("app", "import_tab", "gallery_tab", "export_tab", "library_picker", "book_views",
              "widgets", "keyboard", "metadata_dialog", "reader", "reader_window",
              "reader_launcher", "book_opener", "library_edits", "selection")
ENUM_NAMES = {"Colors", "Icons", "FontWeight", "CrossAxisAlignment", "ScrollMode", "StackFit",
              "ThemeMode", "FilePickerFileType", "TextOverflow", "TextAlign", "BoxFit",
              "Alignment", "MainAxisAlignment", "Border", "VisualDensity", "MouseCursor",
              "WindowEventType"}


class _Name(str):
    """Fake enum value; also works as a factory (ft.Border.all(1, colour))."""

    def __call__(self, *args, **kwargs):
        return self


class _Enum:
    def __getattr__(self, name):
        return _Name(name)


class FakeControl:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.value = args[0] if args and isinstance(args[0], str) else None
        self.controls = []
        self.disabled = False
        self.visible = True
        self.__dict__.update(kwargs)


class FakeFlet(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Enum() if name in ENUM_NAMES else FakeControl


class FakePage:
    def __init__(self):
        self.services, self.overlay, self.added, self.dialogs = [], [], [], []
        self.tasks = []  # page.run_task(...): recorded, not run
        self.window = SimpleNamespace()

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        pass

    def run_task(self, handler, *args):
        self.tasks.append((handler, args))

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        """Like Flet: closes the top dialog; with none open it does nothing (None)."""
        return self.dialogs.pop() if self.dialogs else None


class FakePicker:
    def __init__(self, files=None, folder=None, error=None):
        self.files, self.folder, self.error = files, folder, error

    async def pick_files(self, **_kwargs):
        if self.error:
            raise self.error
        return self.files

    async def get_directory_path(self, **_kwargs):
        if self.error:
            raise self.error
        return self.folder


def log_lines(app):
    return [control.value for control in app.log_view.controls]


def open_library(app, make_library, tmp_path, name="Biblioteca"):
    root = make_library(tmp_path / name)
    assert asyncio.run(app.open_library(root))
    return root


# ---------------------------------------------------------------- gallery gestures

def menu_item(card, name):
    """An item of the right-button menu of a card."""
    [item] = [item for item in card.control.secondary_items if item.content == name]
    return item


def gestures(card):
    """What the card does with the mouse: (click, double click, right button > Abrir)."""
    detector = card.control.content

    def click(event):
        card._last_tap = None  # a single click, far from any other
        detector.on_tap_down(event)

    def double_click(event):
        click(event)
        detector.on_tap_down(event)

    return click, double_click, menu_item(card, "Abrir").on_click


def press_shift(app, down=True, key="Shift Left"):
    """Presses/releases Shift as the window KeyboardListener reports it."""
    (app.keys.on_key_down if down else app.keys.on_key_up)(SimpleNamespace(key=key))


def press_ctrl(app, down=True, key="Control Left"):
    """Presses/releases Ctrl (or "Meta Left": Cmd on macOS)."""
    (app.keys.on_key_down if down else app.keys.on_key_up)(SimpleNamespace(key=key))


def page_key(key, shift=False, ctrl=False, meta=False):
    """What page.on_keyboard_event receives (Flet's KeyboardEvent has all four flags)."""
    return SimpleNamespace(key=key, shift=shift, ctrl=ctrl, alt=False, meta=meta)


def selected_titles(gallery):
    """Titles of the selected books, in the order shown."""
    return [book.title for book in gallery.view if book.id in gallery.selection]


def open_edit_dialog(app, card):
    """Right button on the card, then Editar metadados; returns the MetadataDialog."""
    card.control.content.on_secondary_tap_down(None)
    menu_item(card, "Editar metadados").on_click(None)
    return app.page.dialogs[-1].actions[-1].on_click.__self__  # Salvar -> its dialog


def press_open_book(app, book):
    """Abrir livro in the details window of the book."""
    app.gallery.show_details(book, None)
    asyncio.run(app.page.dialogs[-1].actions[0].on_click(None))
