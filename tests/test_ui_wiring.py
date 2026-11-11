"""Testa a ligação da interface usando um 'Flet de mentira'.

Isto NÃO valida a aparência nem a API real do Flet: só confere que a lógica do
app (botões -> funções, progresso em thread, paginação, edição) funciona.
"""
import asyncio
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from pdf2calibre.models import BookEntry, Status
from pdf2calibre.settings import Settings

ENUM_NAMES = {"Colors", "Icons", "FontWeight", "CrossAxisAlignment", "ScrollMode",
              "ThemeMode", "FilePickerFileType"}


class _Enum:
    def __getattr__(self, name):
        return name


class Control:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.value = args[0] if args and isinstance(args[0], str) else None
        self.controls = []
        self.disabled = False
        self.__dict__.update(kwargs)


class FakeFlet(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Enum() if name in ENUM_NAMES else Control


class FakePage:
    def __init__(self):
        self.services, self.overlay, self.added = [], [], []
        self.updates = 0
        self.window = SimpleNamespace()

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1


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
    monkeypatch.setitem(sys.modules, "flet", FakeFlet("flet"))
    monkeypatch.delitem(sys.modules, "pdf2calibre.ui", raising=False)
    module = importlib.import_module("pdf2calibre.ui")
    monkeypatch.setattr(module, "load_settings", lambda: Settings())
    monkeypatch.setattr(module, "save_settings", lambda _settings: True)
    yield module
    sys.modules.pop("pdf2calibre.ui", None)


@pytest.fixture
def app(ui):
    page = FakePage()
    instance = ui.OrganizerApp(page)
    instance.build()
    return instance


def _log_lines(app):
    return [control.value for control in app.log_view.controls]


def test_build_registers_picker_and_adds_content(app):
    assert app.file_picker in app.page.services
    assert len(app.page.added) == 1
    assert app.source_label.value == "Nenhuma origem escolhida."


def test_collect_options_reads_controls(app):
    app.cb_folder.value = False
    app.sw_move.value = True
    app.tags_field.value = " a, ,b "
    options = app._collect_options(dry_run=True)
    assert options.folder_per_book is False
    assert options.mode.value == "mover"
    assert options.tags == ["a", "b"]
    assert options.dry_run is True


def test_format_size(ui):
    assert ui.format_size(500) == "500 B"
    assert ui.format_size(1536) == "1,5 KB"
    assert ui.format_size(5 * 1024 ** 3) == "5,0 GB"


def test_toggle_and_edit(app):
    entry = BookEntry(Path("x.pdf"), title="T", author="A", status=Status.DUPLICATE, selected=False)
    app._toggle(entry, True)
    assert entry.status is Status.READY and entry.selected
    app._edit(entry, "title", "  Novo ")
    assert entry.title == "Novo" and entry.title_origin == "manual"


def test_pagination(app):
    app.entries = [BookEntry(Path(f"{i}.pdf"), title=f"T{i}", author="A") for i in range(85)]
    app._refresh_list()
    assert len(app.list_view.controls) == 40
    assert app.page_label.value == "Página 1 de 3"
    assert app.prev_btn.disabled and not app.next_btn.disabled
    app.on_next(None)
    app.on_next(None)
    app.on_next(None)  # não passa da última
    assert app.page_label.value == "Página 3 de 3"
    assert len(app.list_view.controls) == 5
    assert app.next_btn.disabled
    app.on_prev(None)
    assert app.page_label.value == "Página 2 de 3"


def test_pick_files_adds_sources(app, tmp_path):
    app.file_picker = FakePicker(files=[SimpleNamespace(path=str(tmp_path / "a.pdf")),
                                        SimpleNamespace(path=None)])
    asyncio.run(app.on_pick_files(None))
    assert app.sources == [tmp_path / "a.pdf"]
    assert "1 origem" in app.source_label.value


def test_pick_failure_is_logged_not_raised(app):
    app.file_picker = FakePicker(error=RuntimeError("sem suporte"))
    asyncio.run(app.on_pick_files(None))
    asyncio.run(app.on_pick_folder(None))
    assert sum("indisponível" in line for line in _log_lines(app)) == 2


def test_pick_destination_sets_field(app, tmp_path):
    app.file_picker = FakePicker(folder=str(tmp_path))
    asyncio.run(app.on_pick_destination(None))
    assert app.dest_field.value == str(tmp_path)


def test_add_typed_path(app, tmp_path):
    app.source_input.value = f' "{tmp_path}" '
    app.on_add_typed(None)
    assert app.sources == [tmp_path]
    app.source_input.value = str(tmp_path / "nao-existe")
    app.on_add_typed(None)
    assert any("não encontrado" in line for line in _log_lines(app))


def test_scan_without_sources_warns(app):
    asyncio.run(app.on_scan(None))
    assert any("Escolha ao menos" in line for line in _log_lines(app))


def test_organize_requires_analysis_and_destination(app):
    asyncio.run(app.on_run(None))
    app.entries = [BookEntry(Path("x.pdf"))]
    asyncio.run(app.on_run(None))
    lines = _log_lines(app)
    assert any("Analise os PDFs" in line for line in lines)
    assert any("pasta de destino" in line for line in lines)


def test_full_flow_scan_organize_undo(app, tmp_path, make_pdf):
    src = tmp_path / "src"
    make_pdf(src / "Autor Um - Livro Um.pdf", text="1")
    make_pdf(src / "Autor Dois - Livro Dois.pdf", text="2")
    (src / "copia.pdf").write_bytes((src / "Autor Um - Livro Um.pdf").read_bytes())
    dest = tmp_path / "biblioteca"
    app.sources = [src]
    app.dest_field.value = str(dest)

    asyncio.run(app.on_scan(None))
    assert len(app.entries) == 3
    assert [e.status for e in app.entries].count(Status.DUPLICATE) == 1
    assert len(app.list_view.controls) == 3

    asyncio.run(app.on_dry_run(None))
    assert not dest.exists()

    asyncio.run(app.on_run(None))
    books = sorted(p.name for p in dest.rglob("*.pdf"))
    assert books == ["Livro Dois - Autor Dois.pdf", "Livro Um - Autor Um.pdf"]
    assert (dest / "Autor Um" / "Livro Um" / "metadata.opf").is_file()
    assert not app.btn_scan.disabled and app.btn_cancel.disabled  # voltou ao normal

    asyncio.run(app.on_undo(None))
    assert not list(dest.rglob("*.pdf"))
    assert app.entries == []
    assert any("Desfeito: 2 de 2" in line for line in _log_lines(app))


def test_undo_without_manifest(app, tmp_path):
    app.dest_field.value = str(tmp_path)
    asyncio.run(app.on_undo(None))
    assert any("nada para desfazer" in line for line in _log_lines(app))


def test_calibre_import_skipped_without_tool_or_library(app, tmp_path, monkeypatch, ui):
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: None)
    asyncio.run(app._import_into_calibre(app.options))
    assert any("calibredb não encontrado" in line for line in _log_lines(app))
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: tmp_path / "x")
    app.library_field.value = str(tmp_path)
    asyncio.run(app._import_into_calibre(app.options))
    assert any("metadata.db" in line for line in _log_lines(app))


def test_cancel_sets_event(app):
    app.on_cancel(None)
    assert app.cancel_event.is_set()
