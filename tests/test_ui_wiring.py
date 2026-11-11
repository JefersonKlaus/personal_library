"""Testa a ligação da interface usando um 'Flet de mentira'.

Isto NÃO valida a aparência nem a API real do Flet: só confere que a lógica do
app (botões -> funções, progresso em thread, paginação, edição) funciona.
"""
import ast
import asyncio
import inspect
import importlib
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

from pdf2calibre.models import BookEntry, Status
from pdf2calibre.settings import Settings

ENUM_NAMES = {"Colors", "Icons", "FontWeight", "CrossAxisAlignment", "ScrollMode", "StackFit",
              "ThemeMode", "FilePickerFileType", "TextOverflow", "TextAlign", "BoxFit",
              "Alignment", "MainAxisAlignment", "Border"}


class _Name(str):
    """Valor de enum falso; também funciona como fábrica (ft.Border.all(1, cor))."""

    def __call__(self, *args, **kwargs):
        return self


class _Enum:
    def __getattr__(self, name):
        return _Name(name)


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
        self.services, self.overlay, self.added, self.dialogs = [], [], [], []
        self.updates = 0
        self.window = SimpleNamespace()

    def add(self, *controls):
        self.added.extend(controls)

    def update(self):
        self.updates += 1

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
    monkeypatch.setitem(sys.modules, "flet", FakeFlet("flet"))
    monkeypatch.delitem(sys.modules, "pdf2calibre.ui", raising=False)
    monkeypatch.delitem(sys.modules, "pdf2calibre.gallery_ui", raising=False)
    module = importlib.import_module("pdf2calibre.ui")
    monkeypatch.setattr(module, "load_settings", lambda: Settings())
    monkeypatch.setattr(module, "save_settings", lambda _settings: True)
    yield module
    sys.modules.pop("pdf2calibre.ui", None)
    sys.modules.pop("pdf2calibre.gallery_ui", None)


@pytest.fixture
def app(ui, tmp_path):
    page = FakePage()
    instance = ui.PersonalLibraryApp(page)
    instance.gallery.thumb_cache = tmp_path / "thumbs"  # não usa ~/.pdf2calibre nos testes
    instance.build()
    return instance


def _log_lines(app):
    return [control.value for control in app.log_view.controls]


def _sources(tmp_path, make_pdf):
    src = tmp_path / "src"
    make_pdf(src / "Autor Um - Livro Um.pdf", text="1")
    make_pdf(src / "Autor Dois - Livro Dois.pdf", text="2")
    (src / "copia.pdf").write_bytes((src / "Autor Um - Livro Um.pdf").read_bytes())
    return src


def _with_library(app, make_library, tmp_path):
    root = make_library(tmp_path / "Calibre Library")
    asyncio.run(app.gallery.load(str(root)))
    return root


# ---------------------------------------------------------------- janela

def test_build_registers_picker_and_adds_content(app):
    assert app.file_picker in app.page.services
    assert len(app.page.added) == 1
    assert app.source_label.value == "Nenhuma origem escolhida."
    assert app.tabs.length == 3
    tab_bar, tab_view = app.tabs.content.controls
    assert [tab.label for tab in tab_bar.tabs] == ["Importar", "Galeria", "Exportar"]
    assert len(tab_view.controls) == 3
    assert app.btn_import.disabled  # nada analisado e nenhuma biblioteca
    assert app.export_body.controls == [app.export_empty]
    assert "Galeria" in app.import_library_text.value


def test_app_name(ui):
    assert ui.APP_NAME == "Personal Library"


def test_collect_options_reads_controls(app):
    app.cb_recursive.value = False
    app.cb_author_first.value = False
    app.tags_field.value = " a, ,b "
    options = app._collect_options()
    assert options.recursive is False and options.author_first is False
    assert options.tags == ["a", "b"]
    app.cb_folder.value = False
    app.cb_cover.value = False
    export = app._export_options(dry_run=True)
    assert (export.folder_per_book, export.include_cover, export.dry_run) == (False, False, True)


def test_format_size(ui):
    assert ui.format_size(500) == "500 B"
    assert ui.format_size(1536) == "1,5 KB"
    assert ui.format_size(5 * 1024 ** 3) == "5,0 GB"


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


# ---------------------------------------------------------------- aba Importar

def test_toggle_and_edit(app):
    entry = BookEntry(Path("x.pdf"), title="T", author="A", status=Status.DUPLICATE, selected=False)
    app.entries = [entry]
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


def test_adding_sources_analyzes_automatically(app, tmp_path, make_pdf):
    src = _sources(tmp_path, make_pdf)
    app.file_picker = FakePicker(files=[SimpleNamespace(path=str(src / "Autor Um - Livro Um.pdf")),
                                        SimpleNamespace(path=None)])
    asyncio.run(app.on_pick_files(None))
    assert app.sources == [src / "Autor Um - Livro Um.pdf"]
    assert [e.title for e in app.entries] == ["Livro Um"]  # já analisado, sem clicar
    assert app.btn_scan.content == "Analisar de novo"


def test_add_typed_path_and_re_adding_the_same_folder(app, tmp_path, make_pdf):
    src = _sources(tmp_path, make_pdf)
    app.source_input.value = f' "{src}" '
    asyncio.run(app.on_add_typed(None))
    assert app.sources == [src] and len(app.entries) == 3
    assert [e.status for e in app.entries].count(Status.DUPLICATE) == 1
    app.entries[0].title = "Editado"  # adicionar a mesma pasta não apaga a revisão
    app.source_input.value = str(src)
    asyncio.run(app.on_add_typed(None))
    assert app.entries[0].title == "Editado"
    app.entries.clear()  # ...mas sem nada analisado, analisa de novo
    app.source_input.value = str(src)
    asyncio.run(app.on_add_typed(None))
    assert len(app.entries) == 3
    app.source_input.value = str(tmp_path / "nao-existe")
    asyncio.run(app.on_add_typed(None))
    assert any("não encontrado" in line for line in _log_lines(app))


def test_pick_failure_is_logged_not_raised(app):
    app.file_picker = FakePicker(error=RuntimeError("sem suporte"))
    asyncio.run(app.on_pick_files(None))
    asyncio.run(app.on_pick_folder(None))
    assert sum("indisponível" in line for line in _log_lines(app)) == 2


def test_scan_without_sources_warns(app):
    asyncio.run(app.on_scan(None))
    assert any("Escolha ao menos" in line for line in _log_lines(app))


def test_import_needs_library_and_calibredb(app, tmp_path, make_pdf, make_library, monkeypatch,
                                           ui):
    app.sources = [_sources(tmp_path, make_pdf)]
    asyncio.run(app.on_scan(None))
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: None)
    asyncio.run(app.on_import(None))
    assert any("biblioteca do Calibre na aba Galeria" in line for line in _log_lines(app))
    _with_library(app, make_library, tmp_path)
    assert "calibredb não encontrado" in app.import_library_text.value
    asyncio.run(app.on_import(None))
    assert any("calibredb não encontrado" in line for line in _log_lines(app))
    assert app.btn_import.disabled and app.calibredb_field.visible


def test_import_flow_updates_list_and_gallery(app, tmp_path, make_pdf, make_library,
                                              monkeypatch, ui):
    root = _with_library(app, make_library, tmp_path)
    app.sources = [_sources(tmp_path, make_pdf)]
    asyncio.run(app.on_scan(None))
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: tmp_path / "calibredb")
    app.refresh_library_info()
    assert not app.btn_import.disabled
    assert app.import_library_text.value.startswith(f"Os livros vão para {root}")
    calls = []

    def fake_import(entries, library, options, tool, progress=None, cancel=None):
        calls.append((library, tool))
        done = [e for e in entries if e.usable]
        for number, entry in enumerate(done, start=10):
            entry.status = Status.DONE
            entry.note(f"na biblioteca (id {number})")
        return ui.library_import.ImportReport(total=len(done), added=len(done),
                                              book_ids=list(range(10, 10 + len(done))))

    monkeypatch.setattr(ui.library_import, "import_to_library", fake_import)
    loads = []
    original = app.gallery.load

    async def spy(folder):
        loads.append(folder)
        await original(folder)

    monkeypatch.setattr(app.gallery, "load", spy)
    asyncio.run(app.on_import(None))
    assert calls == [(root, tmp_path / "calibredb")]
    assert [e.status for e in app.entries].count(Status.DONE) == 2
    assert loads == [str(root)]  # a galeria recarrega sozinha
    assert _log_lines(app)[-1].startswith("2 de 2 livro(s) adicionados")
    assert app.btn_import.disabled  # nada mais para importar


def test_undo_import(app, tmp_path, make_library, monkeypatch, ui):
    _with_library(app, make_library, tmp_path)
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: tmp_path / "calibredb")
    asyncio.run(app.on_undo_import(None))
    assert any("Não há importação" in line for line in _log_lines(app))
    entry = BookEntry(Path("x.pdf"), title="T", author="A", status=Status.DONE,
                      notes=["na biblioteca (id 9)"])
    app.entries = [entry]
    monkeypatch.setattr(ui.library_import, "latest_import", lambda _lib: tmp_path / "r.json")
    monkeypatch.setattr(ui.library_import, "undo_import", lambda _r, _t: (1, ""))
    asyncio.run(app.on_undo_import(None))
    assert entry.status is Status.READY and entry.notes == []
    assert any("Importação desfeita: 1" in line for line in _log_lines(app))


# ---------------------------------------------------------------- aba Exportar

def test_export_lists_library_books_all_selected(app, make_library, tmp_path):
    _with_library(app, make_library, tmp_path)
    assert app.export_body.controls == [app.export_list]
    assert len(app.export_list.controls) == 4
    assert app.export_summary.value == "4 de 4 livro(s) marcados para exportar"


def test_export_filter_and_select_all(app, make_library, tmp_path):
    _with_library(app, make_library, tmp_path)
    app.export_search.value = "clássicos"
    app.on_export_search(None)
    assert len(app.export_list.controls) == 2
    app.on_export_select_all(False)  # só os do filtro
    assert len(app.export_selected) == 2
    assert "2 no filtro" in app.export_summary.value
    app.on_export_select_all(True)
    assert len(app.export_selected) == 4


def test_export_dry_run_then_real_then_undo(app, make_library, tmp_path):
    _with_library(app, make_library, tmp_path)
    hobbit = next(b for b in app.gallery.books if b.title == "The Hobbit")
    app._export_toggle(hobbit, False)
    dest = tmp_path / "pendrive"
    app.dest_field.value = str(dest)
    asyncio.run(app.on_export_dry_run(None))
    assert not dest.exists()
    assert app.export_state[1][1].startswith("iria para")
    asyncio.run(app.on_export(None))
    pdfs = sorted(p.name for p in dest.rglob("*.pdf"))
    assert len(pdfs) == 3 and "The Hobbit - J. R. R. Tolkien.pdf" not in pdfs
    assert len(list(dest.rglob("*.opf"))) == 3
    assert _log_lines(app)[-1] == f"3 livro(s) exportados para {dest}."
    assert "3 exportado(s)" in app.export_summary.value
    asyncio.run(app.on_undo_export(None))
    assert not list(dest.rglob("*.pdf"))
    assert app.export_state == {}


def test_export_requires_library_selection_and_destination(app, make_library, tmp_path):
    asyncio.run(app.on_export(None))
    assert any("biblioteca na aba Galeria" in line for line in _log_lines(app))
    _with_library(app, make_library, tmp_path)
    app.on_export_select_all(False)
    asyncio.run(app.on_export(None))
    assert any("Marque ao menos" in line for line in _log_lines(app))
    app.on_export_select_all(True)
    app.dest_field.value = ""
    asyncio.run(app.on_export(None))
    assert any("pasta de destino" in line for line in _log_lines(app))


def test_export_refuses_calibre_library_as_destination(app, make_library, tmp_path):
    root = _with_library(app, make_library, tmp_path)
    app.dest_field.value = str(root / "copia")
    asyncio.run(app.on_export(None))
    assert any("dentro de uma biblioteca do Calibre" in line for line in _log_lines(app))


def test_reloading_library_keeps_selection_and_selects_new_books(app, make_library, tmp_path):
    root = _with_library(app, make_library, tmp_path)
    app.export_selected.discard(1)
    books = app.gallery.books
    new_book = type(books[0])(id=99, title="Novo")
    app.on_library_loaded(books + [new_book], changed=False)
    assert 1 not in app.export_selected and 99 in app.export_selected
    app.on_library_loaded(books, changed=True)  # outra biblioteca: tudo marcado
    assert app.export_selected == {b.id for b in books}
    assert root


def test_undo_export_without_manifest(app, tmp_path):
    app.dest_field.value = str(tmp_path)
    asyncio.run(app.on_undo_export(None))
    assert any("Não há exportação" in line for line in _log_lines(app))


# ---------------------------------------------------------------- Galeria

def test_gallery_loads_library_as_cover_grid(app, make_library, tmp_path):
    root = make_library(tmp_path / "Calibre Library")
    asyncio.run(app.gallery.load(str(root)))
    gallery = app.gallery
    assert gallery.body.controls == [gallery.grid]
    assert len(gallery.grid.controls) == 4
    assert gallery.count_text.value == "4 livro(s)"
    assert "4 livro(s) em" in gallery.library_status.value
    assert app.settings.library == str(root)  # lembrado para a próxima vez
    assert gallery.view[0].title == "Física Básica"  # mais recentes primeiro


def test_gallery_search_and_sort(app, make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    gallery = app.gallery
    asyncio.run(gallery.load(str(root)))
    gallery.search_field.value = "cortico"
    asyncio.run(gallery.on_search(None))
    assert [b.title for b in gallery.view] == ["O Cortiço"]
    assert gallery.count_text.value == "1 de 4 livro(s)"
    gallery.search_field.value = "xyz"
    asyncio.run(gallery.on_search(None))
    assert gallery.body.controls == [gallery.empty_state]
    assert "Nenhum livro" in gallery.empty_text.value
    gallery.search_field.value = ""
    gallery.sort_dropdown.value = "title"
    asyncio.run(gallery.on_sort(None))
    assert gallery.view[0].title == "Dom Casmurro"
    assert app.settings.gallery_sort == "title"


def test_gallery_rejects_folder_without_metadata_db(app, tmp_path):
    asyncio.run(app.gallery.load(str(tmp_path)))
    assert app.gallery.library is None
    assert app.gallery.body.controls == [app.gallery.empty_state]
    assert "metadata.db" in app.gallery.library_status.value


def test_gallery_details_dialog(app, make_library, tmp_path, monkeypatch, ui):
    root = make_library(tmp_path / "lib")
    gallery = app.gallery
    asyncio.run(gallery.load(str(root)))
    dom = next(b for b in gallery.books if b.title == "Dom Casmurro")
    rows = dict(gallery.details_rows(dom))
    assert rows["Série"] == "Clássicos [1]"
    assert rows["Publicado"] == "1899"
    assert rows["Identificadores"] == "isbn:9788535910667"
    gallery.show_details(dom, None)
    assert len(app.page.dialogs) == 1
    opened = []
    monkeypatch.setattr(sys.modules["pdf2calibre.gallery_ui"], "open_path", opened.append)
    open_book = app.page.dialogs[0].actions[1]
    open_book.on_click(None)
    assert opened == [dom.main_file(root)]
    app.page.dialogs[0].actions[2].on_click(None)  # Fechar
    assert app.page.dialogs == []


def test_gallery_pagination(app, make_library, tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules["pdf2calibre.gallery_ui"], "GALLERY_PAGE_SIZE", 3)
    asyncio.run(app.gallery.load(str(make_library(tmp_path / "lib"))))
    gallery = app.gallery
    assert len(gallery.grid.controls) == 3 and gallery.page_label.value == "Página 1 de 2"
    asyncio.run(gallery.on_next(None))
    assert len(gallery.grid.controls) == 1 and gallery.next_btn.disabled


def test_tab_change_loads_saved_library(app, make_library, tmp_path):
    root = make_library(tmp_path / "lib")
    app.gallery.library_field.value = str(root)
    app.tabs.selected_index = 2  # Exportar também precisa dos livros
    asyncio.run(app.on_tab_change(None))
    assert app.gallery.library == root
    assert len(app.export_list.controls) == 4


def test_pick_destination_sets_field(app, tmp_path):
    app.file_picker = FakePicker(folder=str(tmp_path))
    asyncio.run(app.on_pick_destination(None))
    assert app.dest_field.value == str(tmp_path)


# ---------------------------------------------------------------- padrão do nome (aba Importar)

def test_pattern_preview_uses_first_file(app, tmp_path, make_pdf):
    pdf = make_pdf(tmp_path / "manga" / "One Punch Man - Vol 18.pdf")
    app.sources = [pdf]
    app.pattern_field.value = "@name - @vol; @auth=ONE"
    assert app.update_pattern_preview()
    assert "Título: One Punch Man ·" in app.pattern_preview.value
    assert "Vol.: 18" in app.pattern_preview.value
    assert "Série: One Punch Man (de @name" in app.pattern_preview.value
    assert "Autor: ONE (fixo)" in app.pattern_preview.value
    app.pattern_field.value = "@name - @auth"
    app.update_pattern_preview()
    assert "Autor: Vol 18 (parece um volume: use @vol)" in app.pattern_preview.value
    app.pattern_field.value = "@vol - @auth"
    assert not app.update_pattern_preview()
    assert app.pattern_preview.value.startswith("Inválido")
    app.sources = [make_pdf(tmp_path / "outros" / "Machado de Assis - Dom Casmurro.pdf")]
    app.pattern_field.value = "@name - @vol - @auth"  # sem volume: fora do padrão
    app.update_pattern_preview()
    assert "não segue o padrão; no automático" in app.pattern_preview.value
    assert "Título: Dom Casmurro" in app.pattern_preview.value


def test_invalid_pattern_blocks_analysis(app, tmp_path, make_pdf):
    app.sources = [_sources(tmp_path, make_pdf)]
    app.pattern_field.value = "@name - @name"
    asyncio.run(app.on_scan(None))
    assert app.entries == []
    assert any("Inválido" in line for line in _log_lines(app))


def test_preset_applies_pattern_and_reanalyzes(app, tmp_path, make_pdf):
    src = tmp_path / "manga"
    make_pdf(src / "Naruto - 03 - Masashi Kishimoto.pdf")
    app.sources = [src]
    handler = app._preset_handler("@name - @vol - @auth")
    assert inspect.iscoroutinefunction(handler)  # o Flet só espera funções async
    asyncio.run(handler(None))
    assert app.pattern_field.value == "@name - @vol - @auth"
    assert app.options.filename_pattern == "@name - @vol - @auth"
    assert [(e.title, e.author, e.series_index) for e in app.entries] == [
        ("Naruto", "Masashi Kishimoto", 3)]


def test_series_and_volume_can_be_edited(app):
    entry = BookEntry(Path("x.pdf"), title="T", author="A")
    app._edit(entry, "series", " One Punch Man ")
    app._edit(entry, "series_index", "18")
    app._edit(entry, "series_index", "1x")  # digitando: mantém o último válido
    assert (entry.series, entry.series_index) == ("One Punch Man", 18)
    app._edit(entry, "series_index", "")
    assert entry.series_index is None


def test_no_lambda_calls_an_async_method():
    """Um lambda que chama método async devolve uma corrotina que o Flet ignora
    (o botão parece não fazer nada). Os handlers async precisam ser async def."""
    for module in ("ui.py", "gallery_ui.py"):
        tree = ast.parse((Path(__file__).parent.parent / "pdf2calibre" / module).read_text(
            encoding="utf-8"))
        async_methods = {node.name for node in ast.walk(tree)
                         if isinstance(node, ast.AsyncFunctionDef)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Lambda):
                for call in ast.walk(node.body):
                    if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) \
                            and call.func.attr in async_methods:
                        raise AssertionError(f"{module}:{node.lineno} lambda chama "
                                             f"{call.func.attr} (async)")


def test_template_preset_waits_for_the_value(app):
    asyncio.run(app._preset_handler("@name - @vol; @auth=")(None))
    assert app.pattern_field.value == "@name - @vol; @auth="
    assert "Complete o valor" in app.pattern_preview.value
    assert not any("Inválido" in line for line in _log_lines(app))  # nada de erro no registro


# ---------------------------------------------------------------- sem biblioteca: escolher ou criar

@pytest.fixture
def no_known_libraries(ui, monkeypatch):
    monkeypatch.setattr(ui.calibre, "known_libraries", lambda *a: [])


def test_import_tab_asks_for_a_library(app, no_known_libraries):
    app.refresh_library_info()
    assert app.library_setup.visible and not app.library_row.visible
    assert app.setup_title.value == "Nenhuma biblioteca do Calibre escolhida ainda."
    assert app.btn_import.disabled
    app.gallery.library_field.value = "/caminho/que/sumiu"
    app.refresh_library_info()
    assert "não foi encontrada" in app.setup_title.value


def test_not_a_library_message(app, tmp_path, no_known_libraries):
    app.gallery.library_field.value = str(tmp_path)
    app.refresh_library_info()
    assert "não é uma biblioteca do Calibre" in app.setup_title.value


def test_use_a_library_found_in_calibre(app, make_library, tmp_path, monkeypatch, ui):
    root = make_library(tmp_path / "Calibre Library")
    monkeypatch.setattr(ui.calibre, "known_libraries", lambda *a: [root])
    app.refresh_library_info()
    row = app.setup_detected.controls[1]
    use = row.controls[-1]
    assert inspect.iscoroutinefunction(use.on_click)
    asyncio.run(use.on_click(None))
    assert app.gallery.library == root and app.settings.library == str(root)
    assert not app.library_setup.visible and app.library_row.visible


def test_choose_existing_library_accepts_parent_folder(app, make_library, tmp_path,
                                                       no_known_libraries):
    root = make_library(tmp_path / "Documentos" / "Calibre Library")
    app.file_picker = FakePicker(folder=str(tmp_path / "Documentos"))
    asyncio.run(app.on_choose_library(None))
    assert app.gallery.library == root
    app.file_picker = FakePicker(folder=str(tmp_path / "vazia"))
    asyncio.run(app.on_choose_library(None))
    assert any("não é uma biblioteca do Calibre" in line for line in _log_lines(app))
    assert app.gallery.library == root  # continua a anterior


def test_change_library_and_cancel(app, make_library, tmp_path, no_known_libraries):
    root = make_library(tmp_path / "lib")
    asyncio.run(app.use_library(root))
    asyncio.run(app.on_change_library(None))
    assert app.library_setup.visible and app.btn_setup_cancel.visible
    assert app.setup_title.value == f"Trocar de biblioteca (atual: {root})"
    app.on_cancel_setup(None)
    assert not app.library_setup.visible


def test_create_new_library(app, tmp_path, monkeypatch, ui, make_library, no_known_libraries):
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: None)
    asyncio.run(app.on_create_library(None))
    assert any("Calibre instalado" in line for line in _log_lines(app))

    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: tmp_path / "calibredb")
    created = []

    def fake_create(tool, target):
        make_library(target, books=[])
        created.append(target)
        return True, ""

    monkeypatch.setattr(ui.calibre, "create_library", fake_create)
    busy = tmp_path / "Documentos"
    busy.mkdir()
    (busy / "foto.jpg").write_bytes(b"x")
    app.file_picker = FakePicker(folder=str(busy))
    asyncio.run(app.on_create_library(None))
    dialog = app.page.dialogs[-1]
    assert str(busy / "Calibre Library") in [c.value for c in dialog.content.controls]
    create_button = dialog.actions[-1]
    assert inspect.iscoroutinefunction(create_button.on_click)
    asyncio.run(create_button.on_click(None))
    assert created == [busy / "Calibre Library"]
    assert app.gallery.library == busy / "Calibre Library"
    assert not app.library_setup.visible
    assert "Alternar/criar biblioteca" in _log_lines(app)[-1]


def test_create_library_failure_is_reported(app, tmp_path, monkeypatch, ui, no_known_libraries):
    monkeypatch.setattr(ui.calibre, "find_calibredb", lambda _custom=None: tmp_path / "calibredb")
    monkeypatch.setattr(ui.calibre, "create_library",
                        lambda tool, target: (False, "Feche o Calibre e tente de novo."))
    asyncio.run(app.create_library_at(tmp_path / "nova", tmp_path / "calibredb"))
    assert "Feche o Calibre" in _log_lines(app)[-1]
    assert app.gallery.library is None
