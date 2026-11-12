"""Fábrica de PDFs de teste (gerados na hora; nada de arquivos reais)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from personal_library.library.manager import DATABASE_FILE  # noqa: E402
from personal_library.models import ImportOptions  # noqa: E402


def _make_pdf(path: Path, title: str | None = None, author: str | None = None,
              text: str = "conteudo") -> Path:
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    if title is not None:
        pdf.setTitle(title)
    if author is not None:
        pdf.setAuthor(author)
    pdf.drawString(72, 720, text)
    pdf.save()
    return path


@pytest.fixture
def make_pdf():
    return _make_pdf


@pytest.fixture
def options() -> ImportOptions:
    return ImportOptions(workers=2)


# ---------------------------------------------------------------- biblioteca

# Subconjunto do esquema real do banco da biblioteca, com os mesmos nomes de tabelas.
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
    # título, autores, sort, author_sort, adicionado, publicado, série, etiquetas, capa
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


def _make_library(root: Path, books=SAMPLE_BOOKS) -> Path:
    """Cria uma biblioteca: banco de dados + Autor/Título (id)/."""
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


@pytest.fixture
def make_library():
    return _make_library


# ---------------------------------------------------------------- interface (Flet de mentira)
#
# Valida a lógica de ligação da interface (botões -> funções, estado, mensagens), NÃO a
# aparência nem a API real do Flet.

import asyncio  # noqa: E402
import importlib  # noqa: E402
import types  # noqa: E402
from types import SimpleNamespace  # noqa: E402

UI_MODULES = ("app", "import_tab", "gallery_tab", "export_tab", "library_picker", "book_views",
              "widgets")
ENUM_NAMES = {"Colors", "Icons", "FontWeight", "CrossAxisAlignment", "ScrollMode", "StackFit",
              "ThemeMode", "FilePickerFileType", "TextOverflow", "TextAlign", "BoxFit",
              "Alignment", "MainAxisAlignment", "Border", "VisualDensity", "MouseCursor"}


class _Name(str):
    """Valor de enum falso; também funciona como fábrica (ft.Border.all(1, cor))."""

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
        self.window = SimpleNamespace()

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        pass

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        self.dialogs.pop()


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


@pytest.fixture
def ui(monkeypatch):
    """Os módulos da interface carregados com o Flet de mentira."""
    from personal_library.settings import Settings

    monkeypatch.setitem(sys.modules, "flet", FakeFlet("flet"))
    for name in UI_MODULES:
        monkeypatch.delitem(sys.modules, f"personal_library.ui.{name}", raising=False)
    modules = {name: importlib.import_module(f"personal_library.ui.{name}") for name in UI_MODULES}
    monkeypatch.setattr(modules["app"], "load_settings", lambda: Settings())
    monkeypatch.setattr(modules["app"], "save_settings", lambda _settings: True)
    monkeypatch.setattr(modules["library_picker"], "known_libraries", lambda *a: [])
    yield SimpleNamespace(**modules)
    for name in UI_MODULES:
        sys.modules.pop(f"personal_library.ui.{name}", None)


@pytest.fixture
def app(ui, tmp_path):
    instance = ui.app.PersonalLibraryApp(FakePage())
    instance.gallery.thumb_cache = tmp_path / "thumbs"  # não usa a pasta do usuário
    instance.build()
    return instance


@pytest.fixture
def fake_cli(monkeypatch):
    """Troca a ferramenta da biblioteca; `fake_cli.set(None)` simula 'não instalada'."""
    from personal_library.library.cli import LibraryCli

    holder = SimpleNamespace(tool=SimpleNamespace(name="cli"))
    holder.set = lambda tool: setattr(holder, "tool", tool)
    monkeypatch.setattr(LibraryCli, "find", classmethod(lambda cls, custom=None: holder.tool))
    return holder


def log_lines(app):
    return [control.value for control in app.log_view.controls]


def open_library(app, make_library, tmp_path, name="Biblioteca"):
    root = make_library(tmp_path / name)
    assert asyncio.run(app.open_library(root))
    return root
