"""Aba Importar: origens, "Como importar", revisão e importação."""
import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

from conftest import FakePicker, log_lines, open_library

from personal_library import importer
from personal_library.models import BookEntry, Status


def _sources(tmp_path, make_pdf):
    src = tmp_path / "src"
    make_pdf(src / "Autor Um - Livro Um.pdf", text="1")
    make_pdf(src / "Autor Dois - Livro Dois.pdf", text="2")
    (src / "copia.pdf").write_bytes((src / "Autor Um - Livro Um.pdf").read_bytes())
    return src


def test_initial_state(app):
    tab = app.import_tab
    assert tab.source_label.value == "Nenhuma origem escolhida."
    assert tab.btn_import.disabled  # nada analisado e nenhuma biblioteca


def test_collect_options_reads_controls(app):
    tab = app.import_tab
    tab.cb_recursive.value = False
    tab.cb_author_first.value = False
    tab.tags_field.value = " a, ,b "
    tab.pattern_field.value = " @name - @vol "
    options = tab.collect_options()
    assert options.recursive is False and options.author_first is False
    assert options.tags == ["a", "b"] and options.filename_pattern == "@name - @vol"


def test_toggle_and_edit(app):
    tab = app.import_tab
    entry = BookEntry(Path("x.pdf"), title="T", author="A", status=Status.DUPLICATE, selected=False)
    tab.entries = [entry]
    tab.toggle(entry, True)
    assert entry.status is Status.READY and entry.selected
    tab.edit(entry, "title", "  Novo ")
    assert entry.title == "Novo" and entry.title_origin == "manual"


def test_series_and_volume_can_be_edited(app):
    entry = BookEntry(Path("x.pdf"), title="T", author="A")
    app.import_tab.edit(entry, "series", " One Punch Man ")
    app.import_tab.edit(entry, "series_index", "18")
    app.import_tab.edit(entry, "series_index", "1x")  # digitando: mantém o último válido
    assert (entry.series, entry.series_index) == ("One Punch Man", 18)
    app.import_tab.edit(entry, "series_index", "")
    assert entry.series_index is None


def test_pagination(app):
    tab = app.import_tab
    tab.entries = [BookEntry(Path(f"{i}.pdf"), title=f"T{i}", author="A") for i in range(85)]
    tab.refresh_list()
    assert len(tab.list_view.controls) == 40
    assert tab.page_label.value == "Página 1 de 3"
    assert tab.prev_btn.disabled and not tab.next_btn.disabled
    for _ in range(3):
        tab.on_next(None)  # não passa da última
    assert tab.page_label.value == "Página 3 de 3" and len(tab.list_view.controls) == 5
    assert tab.next_btn.disabled
    tab.on_prev(None)
    assert tab.page_label.value == "Página 2 de 3"


def test_adding_sources_analyzes_automatically(app, tmp_path, make_pdf):
    src = _sources(tmp_path, make_pdf)
    app.file_picker = FakePicker(files=[SimpleNamespace(path=str(src / "Autor Um - Livro Um.pdf")),
                                        SimpleNamespace(path=None)])
    asyncio.run(app.import_tab.on_pick_files(None))
    assert app.import_tab.sources == [src / "Autor Um - Livro Um.pdf"]
    assert [e.title for e in app.import_tab.entries] == ["Livro Um"]  # já analisado
    assert app.import_tab.btn_scan.content == "Analisar de novo"


def test_add_typed_path_and_re_adding_the_same_folder(app, tmp_path, make_pdf):
    tab = app.import_tab
    src = _sources(tmp_path, make_pdf)
    tab.source_input.value = f' "{src}" '
    asyncio.run(tab.on_add_typed(None))
    assert tab.sources == [src] and len(tab.entries) == 3
    assert [e.status for e in tab.entries].count(Status.DUPLICATE) == 1
    tab.entries[0].title = "Editado"  # adicionar a mesma pasta não apaga a revisão
    tab.source_input.value = str(src)
    asyncio.run(tab.on_add_typed(None))
    assert tab.entries[0].title == "Editado"
    tab.entries.clear()  # ...mas sem nada analisado, analisa de novo
    tab.source_input.value = str(src)
    asyncio.run(tab.on_add_typed(None))
    assert len(tab.entries) == 3
    tab.source_input.value = str(tmp_path / "nao-existe")
    asyncio.run(tab.on_add_typed(None))
    assert any("não encontrado" in line for line in log_lines(app))


def test_pick_failure_is_logged_not_raised(app):
    app.file_picker = FakePicker(error=RuntimeError("sem suporte"))
    asyncio.run(app.import_tab.on_pick_files(None))
    asyncio.run(app.import_tab.on_pick_folder(None))
    assert sum("indisponível" in line for line in log_lines(app)) == 2


def test_scan_without_sources_warns(app):
    asyncio.run(app.import_tab.on_scan(None))
    assert any("Escolha ao menos" in line for line in log_lines(app))


# ---------------------------------------------------------------- "Como importar"

def test_pattern_preview_uses_first_file(app, tmp_path, make_pdf):
    tab = app.import_tab
    tab.sources = [make_pdf(tmp_path / "manga" / "One Punch Man - Vol 18.pdf")]
    tab.pattern_field.value = "@name - @vol; @auth=ONE"
    assert tab.update_pattern_preview()
    preview = tab.pattern_preview.value
    assert "Título: One Punch Man ·" in preview and "Vol.: 18" in preview
    assert "Série: One Punch Man (de @name" in preview and "Autor: ONE (fixo)" in preview
    tab.pattern_field.value = "@name - @auth"
    tab.update_pattern_preview()
    assert "Autor: Vol 18 (parece um volume: use @vol)" in tab.pattern_preview.value
    tab.pattern_field.value = "@vol - @auth"
    assert not tab.update_pattern_preview()
    assert tab.pattern_preview.value.startswith("Inválido")
    tab.sources = [make_pdf(tmp_path / "outros" / "Machado de Assis - Dom Casmurro.pdf")]
    tab.pattern_field.value = "@name - @vol - @auth"  # sem volume: fora do padrão
    tab.update_pattern_preview()
    assert "não segue o padrão; no automático" in tab.pattern_preview.value
    assert "Título: Dom Casmurro" in tab.pattern_preview.value


def test_invalid_pattern_blocks_analysis(app, tmp_path, make_pdf):
    app.import_tab.sources = [_sources(tmp_path, make_pdf)]
    app.import_tab.pattern_field.value = "@name - @name"
    asyncio.run(app.import_tab.on_scan(None))
    assert app.import_tab.entries == []
    assert any("Inválido" in line for line in log_lines(app))


def test_preset_applies_pattern_and_reanalyzes(app, tmp_path, make_pdf):
    tab = app.import_tab
    make_pdf(tmp_path / "manga" / "Naruto - 03 - Masashi Kishimoto.pdf")
    tab.sources = [tmp_path / "manga"]
    handler = tab._preset_handler("@name - @vol - @auth")
    assert inspect.iscoroutinefunction(handler)  # o Flet só espera funções async
    asyncio.run(handler(None))
    assert tab.options.filename_pattern == "@name - @vol - @auth"
    assert [(e.title, e.author, e.series_index) for e in tab.entries] == [
        ("Naruto", "Masashi Kishimoto", 3)]


def test_template_preset_waits_for_the_value(app):
    asyncio.run(app.import_tab._preset_handler("@name - @vol; @auth=")(None))
    assert app.import_tab.pattern_field.value == "@name - @vol; @auth="
    assert "Complete o valor" in app.import_tab.pattern_preview.value
    assert not any("Inválido" in line for line in log_lines(app))


# ---------------------------------------------------------------- importar

def test_import_needs_library_and_tool(app, tmp_path, make_pdf, make_library, fake_cli):
    tab = app.import_tab
    tab.sources = [_sources(tmp_path, make_pdf)]
    asyncio.run(tab.on_scan(None))
    asyncio.run(tab.on_import(None))
    assert any("Escolha a biblioteca" in line for line in log_lines(app))
    fake_cli.set(None)
    open_library(app, make_library, tmp_path)
    assert tab.cli_text.visible and tab.cli_field.visible  # pede o caminho da ferramenta
    asyncio.run(tab.on_import(None))
    assert any("não encontrado" in line for line in log_lines(app))
    assert tab.btn_import.disabled


def test_import_flow_updates_list_and_gallery(app, tmp_path, make_pdf, make_library,
                                              fake_cli, monkeypatch):
    tab = app.import_tab
    root = open_library(app, make_library, tmp_path)
    tab.sources = [_sources(tmp_path, make_pdf)]
    asyncio.run(tab.on_scan(None))
    assert not tab.btn_import.disabled and not tab.cli_field.visible
    calls = []

    def fake_import(entries, library, options, cli, progress=None, cancel=None):
        calls.append((library, cli))
        done = [e for e in entries if e.usable]
        for number, entry in enumerate(done, start=10):
            entry.status = Status.DONE
        return importer.ImportReport(total=len(done), added=len(done))

    monkeypatch.setattr(importer, "import_books", fake_import)
    opened = []
    original = app.open_library

    async def spy(path):
        opened.append(path)
        return await original(path)

    monkeypatch.setattr(app, "open_library", spy)
    asyncio.run(tab.on_import(None))
    assert calls == [(root, fake_cli.tool)]
    assert [e.status for e in tab.entries].count(Status.DONE) == 2
    assert opened == [root]  # a galeria recarrega sozinha
    assert log_lines(app)[-1].startswith("2 de 2 livro(s) adicionados")
    assert tab.btn_import.disabled  # nada mais para importar


def test_undo_import(app, tmp_path, make_library, fake_cli, monkeypatch):
    tab = app.import_tab
    open_library(app, make_library, tmp_path)
    asyncio.run(tab.on_undo_import(None))
    assert any("Não há importação" in line for line in log_lines(app))
    entry = BookEntry(Path("x.pdf"), title="T", author="A", status=Status.DONE,
                      notes=["na biblioteca (id 9)"])
    tab.entries = [entry]
    monkeypatch.setattr(importer, "latest_import", lambda _lib: tmp_path / "r.json")
    monkeypatch.setattr(importer, "undo_import", lambda _r, _c: (1, ""))
    asyncio.run(tab.on_undo_import(None))
    assert entry.status is Status.READY and entry.notes == []
    assert any("Importação desfeita: 1" in line for line in log_lines(app))


# ---------------------------------------------------------------- Groq AI

def test_ai_fields_follow_the_checkbox(app):
    tab = app.import_tab
    assert not tab.cb_ai.value and not tab.ai_row.visible and not tab.ai_hint.visible
    tab.cb_ai.value = True
    tab.on_ai_toggle(None)
    assert tab.ai_row.visible and tab.ai_hint.visible
    tab.ai_key_field.value = " gsk_abc "
    tab.ai_model_field.value = ""
    tab.store(app.settings)
    assert app.settings.ai_enabled and app.settings.groq_api_key == "gsk_abc"
    assert app.settings.groq_model == "llama-3.3-70b-versatile"  # vazio = modelo padrão


def test_scan_with_ai_needs_the_key(app, tmp_path, make_pdf, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    tab = app.import_tab
    tab.sources = [_sources(tmp_path, make_pdf)]
    tab.cb_ai.value = True
    tab.ai_key_field.value = ""
    asyncio.run(tab.on_scan(None))
    assert any("Informe a chave da API da Groq" in line for line in log_lines(app))
    assert tab.entries == []  # não analisou nada


def test_scan_with_ai_fills_the_review_list(app, tmp_path, make_pdf, monkeypatch):
    from personal_library.groq_client import GroqClient

    sent = []

    def fake_chat(self, system, user, cancel=None):
        sent.append((self.api_key, user))
        return {"title": "Título da IA", "authors": ["Ana Souza"], "series": "Coleção",
                "volume": 2, "year": 2001, "publisher": "Editora", "language": "pt",
                "confidence": 0.9}

    monkeypatch.setattr(GroqClient, "chat_json", fake_chat)
    tab = app.import_tab
    src = tmp_path / "src"
    make_pdf(src / "arquivo qualquer.pdf", text="Primeira página do livro")
    tab.sources = [src]
    tab.cb_ai.value = True
    tab.ai_key_field.value = "gsk_teste"
    asyncio.run(tab.on_scan(None))
    [entry] = tab.entries
    assert (entry.title, entry.author, entry.series, entry.series_index) == (
        "Título da IA", "Ana Souza", "Coleção", 2)
    assert entry.status is Status.READY
    assert any("preenchido pela IA" in note for note in entry.notes)
    assert len(sent) == 1 and sent[0][0] == "gsk_teste" and "Primeira página" in sent[0][1]
    assert any("IA: 1 de 1 preenchido(s)" in line for line in log_lines(app))


def test_ai_failure_keeps_the_app_guess(app, tmp_path, make_pdf, monkeypatch):
    from personal_library.groq_client import GroqClient, GroqError

    def fake_chat(self, system, user, cancel=None):
        raise GroqError("Chave da API recusada", fatal=True)

    monkeypatch.setattr(GroqClient, "chat_json", fake_chat)
    tab = app.import_tab
    tab.sources = [_sources(tmp_path, make_pdf)]
    tab.cb_ai.value = True
    tab.ai_key_field.value = "gsk_errada"
    asyncio.run(tab.on_scan(None))
    assert sorted(e.title for e in tab.entries) == ["Livro Dois", "Livro Um", "copia"]
    lines = log_lines(app)
    assert any("IA interrompida" in line and "recusada" in line for line in lines)
    assert any("IA: 0 de" in line for line in lines)
