"""Importar tab: choose PDFs, check the adjusted data and import into the library."""
from __future__ import annotations

import asyncio
import dataclasses
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from ..core.models import BookEntry, ImportOptions, Status
from ..core.settings import Settings
from ..importing import ai_metadata, analysis, importer
from ..importing.groq_client import DEFAULT_MODEL, GroqClient, resolve_api_key
from ..library.manager import PRODUCT
from ..parsing.import_spec import PATTERN_HELP, PatternError, compile_spec, describe_pattern
from .widgets import (STATUS_COLORS, format_size, option_grid, page_count, pager_controls,
                      section, update_pager)

if TYPE_CHECKING:  # for the editor only; avoids a circular import
    from .app import PersonalLibraryApp

logger = logging.getLogger(__name__)

PAGE_SIZE = 40
LOCKED_STATUSES = (Status.ERROR, Status.DONE, Status.FAILED)
PATTERN_PRESETS = [
    ("", "Automático (deduz título, autor e volume)"),
    ("@name - @vol - @auth", "@name - @vol - @auth"),
    ("@name - @vol; @auth=", "@name - @vol; @auth=… (autor fixo)"),
    ("@auth - @name", "@auth - @name"),
    ("@name - @auth", "@name - @auth"),
    ("@auth - @name (@year)", "@auth - @name (@year)"),
]


class ImportTab:
    """Controls and actions of the Importar tab."""

    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        settings = app.settings
        opts = settings.get_options()
        self.options = opts
        self.sources: list[Path] = [Path(p) for p in settings.last_sources if Path(p).exists()]
        self.entries: list[BookEntry] = []
        self.page_index = 0
        # 1. Choose the PDFs
        self.source_label = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.source_input = ft.TextField(label="Colar caminho (pasta ou PDF)", dense=True,
                                         expand=True, on_submit=self.on_add_typed)
        self.cb_recursive = ft.Checkbox(label="Incluir subpastas", value=opts.recursive)
        self.cb_dupes = ft.Checkbox(label="Ignorar arquivos idênticos", value=opts.skip_duplicates)
        self.cb_pdf_meta = ft.Checkbox(label="Preferir metadados de dentro do PDF",
                                       value=opts.prefer_pdf_metadata)
        self.cb_author_first = ft.Checkbox(
            label="Automático: autor vem primeiro", value=opts.author_first,
            tooltip="Só vale sem padrão: 'Autor - Título' em vez de 'Título - Autor'.")
        # AI (Groq): fills in the data book by book
        self.cb_ai = ft.Checkbox(label="Usar Groq AI para preencher os dados",
                                 value=settings.ai_enabled, on_change=self.on_ai_toggle)
        self.ai_key_field = ft.TextField(
            label="Chave da API da Groq", value=settings.groq_api_key, password=True,
            can_reveal_password=True, dense=True, expand=True,
            hint_text="gsk_… (crie em console.groq.com)")
        self.ai_model_field = ft.TextField(label="Modelo", value=settings.groq_model,
                                           dense=True, width=260)
        self.ai_hint = ft.Text(
            "Ao analisar, cada PDF é enviado à Groq, um por vez: nome do arquivo, metadados, "
            "número de páginas, o que o app deduziu e o texto das primeiras páginas (o PDF "
            "em si não é enviado). A chave fica salva nas preferências deste computador.",
            size=11, color=ft.Colors.GREY_700)
        # 2. Check the data
        self.pattern_field = ft.TextField(
            label="Como importar: parâmetros, delimitadores e valores fixos (vazio = automático)",
            hint_text="ex.: @name - @vol - @auth   ou   @name - @vol; @auth=ONE",
            value=opts.filename_pattern, dense=True, expand=True,
            on_change=self.on_pattern_change, on_submit=self.on_apply_pattern)
        self.btn_apply_pattern = ft.FilledTonalButton("Aplicar", icon=ft.Icons.CHECK,
                                                      on_click=self.on_apply_pattern)
        self.pattern_preview = ft.Text(size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.btn_scan = ft.OutlinedButton("Analisar", icon=ft.Icons.REFRESH, on_click=self.on_scan)
        self.summary_text = ft.Text(weight=ft.FontWeight.BOLD)
        self.list_view = ft.ListView(controls=[], spacing=6, expand=True)
        self.empty_text = ft.Text(
            "Adicione PDFs ou uma pasta: título e autor são lidos e ajustados automaticamente. "
            "Confira aqui antes de importar.", size=13, color=ft.Colors.GREY_700)
        self.prev_btn, self.page_label, self.next_btn = pager_controls(self.on_prev, self.on_next)
        # 3. Import into the library
        self.tags_field = ft.TextField(
            label="Etiquetas para os livros importados (separadas por vírgula)",
            value=", ".join(opts.tags), dense=True, expand=True)
        self.btn_import = ft.FilledButton("Importar para a biblioteca", icon=ft.Icons.LIBRARY_ADD,
                                          on_click=self.on_import, disabled=True)
        self.btn_undo_import = ft.OutlinedButton("Desfazer última importação", icon=ft.Icons.UNDO,
                                                 on_click=self.on_undo_import)
        self.cli_text = ft.Text(size=12, color=ft.Colors.ORANGE_800)
        self.cli_field = ft.TextField(
            label=f"Caminho do {PRODUCT} (pasta de instalação ou a ferramenta de linha de comando)",
            value=settings.cli_path, dense=True, on_change=self.on_cli_change)
        app.register_actions(self.btn_scan, self.btn_apply_pattern, self.btn_import,
                             self.btn_undo_import)

    # ================================================================== building

    def build(self) -> ft.Control:
        pick_row = ft.Row(controls=[
            ft.FilledTonalButton("Adicionar PDFs…", icon=ft.Icons.PICTURE_AS_PDF,
                                 on_click=self.on_pick_files),
            ft.FilledTonalButton("Adicionar pasta…", icon=ft.Icons.FOLDER_OPEN,
                                 on_click=self.on_pick_folder),
            self.source_input,
            ft.OutlinedButton("Adicionar", on_click=self.on_add_typed),
            ft.TextButton("Limpar", on_click=self.on_clear),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        options = option_grid(self.cb_recursive, self.cb_dupes, self.cb_pdf_meta,
                              self.cb_author_first)
        self.ai_row = ft.Row(controls=[self.ai_key_field, self.ai_model_field],
                             vertical_alignment=ft.CrossAxisAlignment.CENTER)
        presets = ft.PopupMenuButton(
            content=ft.Row(controls=[ft.Text("Modelos", size=13),
                                     ft.Icon(ft.Icons.ARROW_DROP_DOWN)], tight=True, spacing=0),
            tooltip="Padrões comuns",
            items=[ft.PopupMenuItem(content=label, on_click=self._preset_handler(preset))
                   for preset, label in PATTERN_PRESETS])
        pattern_row = ft.Row(controls=[
            self.pattern_field, presets, self.btn_apply_pattern,
            ft.IconButton(icon=ft.Icons.INFO_OUTLINE, tooltip=PATTERN_HELP),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        review_actions = ft.Row(controls=[self.summary_text, ft.Container(expand=True),
                                          self.btn_scan],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.review_body = ft.Column(controls=[self.empty_text], expand=True)
        pager = ft.Row(controls=[self.prev_btn, self.page_label, self.next_btn], spacing=12)
        import_row = ft.Row(controls=[self.tags_field, self.btn_import, self.btn_undo_import],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        picker = self.app.library_picker
        return ft.Container(padding=12, expand=True, content=ft.Column(controls=[
            section("1. Escolha os PDFs", pick_row, self.source_label, options, self.cb_ai,
                    self.ai_row, self.ai_hint),
            section("2. Confira os dados (ajustados automaticamente)", pattern_row,
                    self.pattern_preview, review_actions, self.review_body, pager, expand=True),
            section("3. Importar para a biblioteca", picker.panel, import_row,
                    picker.current_row, self.cli_text, self.cli_field),
        ], spacing=10, expand=True))

    def refresh(self) -> None:
        """Refreshes everything that depends on the state (sources, pattern, list, library)."""
        self._show_ai_fields()
        self._update_sources_label()
        self.update_pattern_preview()
        self.refresh_list()
        self.refresh_library()

    # ================================================================== state

    def collect_options(self) -> ImportOptions:
        tags = [tag.strip() for tag in (self.tags_field.value or "").split(",") if tag.strip()]
        self.options = dataclasses.replace(
            self.options,
            recursive=bool(self.cb_recursive.value),
            skip_duplicates=bool(self.cb_dupes.value),
            prefer_pdf_metadata=bool(self.cb_pdf_meta.value),
            author_first=bool(self.cb_author_first.value),
            filename_pattern=(self.pattern_field.value or "").strip(),
            tags=tags)
        return self.options

    def store(self, settings: Settings) -> None:
        settings.last_sources = [str(path) for path in self.sources]
        settings.cli_path = (self.cli_field.value or "").strip()
        settings.ai_enabled = bool(self.cb_ai.value)
        settings.groq_api_key = (self.ai_key_field.value or "").strip()
        settings.groq_model = (self.ai_model_field.value or "").strip() or DEFAULT_MODEL
        settings.set_options(self.options)

    # ================================================================== AI (Groq)

    def _show_ai_fields(self) -> None:
        self.ai_row.visible = self.ai_hint.visible = bool(self.cb_ai.value)

    def on_ai_toggle(self, _event: Any) -> None:
        self._show_ai_fields()
        self.app.save()
        self.app.page.update()

    def groq_client(self) -> GroqClient | None:
        """The Groq client if "Usar Groq AI" is ticked; None if it is not.

        Raises ValueError (message ready to be shown) if the key is missing."""
        if not self.cb_ai.value:
            return None
        key = resolve_api_key(self.ai_key_field.value or "")
        if not key:
            raise ValueError("Informe a chave da API da Groq (ou desmarque Usar Groq AI).")
        return GroqClient(key, (self.ai_model_field.value or "").strip() or DEFAULT_MODEL)

    async def _fill_with_ai(self, entries: list[BookEntry], client: GroqClient,
                            options: ImportOptions) -> str:
        """Queries the AI book by book; returns the summary for the final message."""
        spec = compile_spec(options.filename_pattern)
        fixed = spec.fixed if spec is not None else {}
        report = await self.app.run_job(ai_metadata.fill_with_ai, entries, client, fixed,
                                        options.unknown_author, label="Consultando a IA")
        self.app.log_errors(report.errors)
        if report.stopped:
            self.app.log(f"IA interrompida: {report.stopped}", True)
        message = f"IA: {report.done} de {report.total} preenchido(s)"
        if report.failed:
            message += f", {report.failed} sem resposta (ficaram com os dados do app)"
        return message + (" (cancelado)" if report.cancelled else "")

    def refresh_library(self) -> None:
        """Was the library tool found? And can the Importar button be used?"""
        cli = self.app.cli()
        self.cli_text.value = "" if cli else (f"{PRODUCT} não encontrado: instale-o ou informe o "
                                              "caminho abaixo.")
        self.cli_text.visible = self.cli_field.visible = cli is None
        self.refresh_import_button()

    def refresh_import_button(self) -> None:
        ready = any(entry.usable for entry in self.entries)
        self.btn_import.disabled = self.app.busy or not (
            ready and self.app.library is not None and self.app.cli() is not None)

    def _update_sources_label(self) -> None:
        if not self.sources:
            self.source_label.value = "Nenhuma origem escolhida."
            return
        names = ", ".join(path.name or str(path) for path in self.sources[:4])
        extra = f" e mais {len(self.sources) - 4}" if len(self.sources) > 4 else ""
        self.source_label.value = f"{len(self.sources)} origem(ns): {names}{extra}"

    def _add_sources(self, paths: list[Path]) -> bool:
        """Adds sources; True if analysing is worthwhile (something new or nothing analysed yet)."""
        added = False
        for path in paths:
            if path not in self.sources:
                self.sources.append(path)
                added = True
        self._update_sources_label()
        self.app.save()
        self.app.page.update()
        return bool(paths) and (added or not self.entries)

    # ================================================================== review list

    def _row(self, entry: BookEntry) -> ft.Control:
        done = entry.status is Status.DONE

        def field(label: str, name: str, value: str, **kwargs: Any) -> ft.TextField:
            return ft.TextField(label=label, value=value, dense=True, read_only=done,
                                on_change=lambda e, item=entry: self.edit(item, name,
                                                                          e.control.value),
                                **kwargs)

        volume = f"{entry.series_index:g}" if entry.series_index is not None else ""
        detail = f"{entry.source.name} · {entry.pages} pág. · {format_size(entry.size)}"
        if entry.notes:
            detail += " · " + "; ".join(entry.notes)
        return ft.Column(controls=[
            ft.Row(controls=[
                ft.Checkbox(value=entry.selected, disabled=entry.status in LOCKED_STATUSES,
                            on_change=lambda e, item=entry: self.toggle(item,
                                                                        bool(e.control.value))),
                field("Título", "title", entry.title, expand=3),
                field("Autor(es), separe com &", "author", entry.author, expand=2),
                field("Série", "series", entry.series, expand=2),
                field("Vol.", "series_index", volume, width=72),
                ft.Text(entry.status.value, color=STATUS_COLORS[entry.status],
                        weight=ft.FontWeight.BOLD, width=84),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text(detail, size=11, color=ft.Colors.GREY_600),
        ], spacing=0)

    def toggle(self, entry: BookEntry, value: bool) -> None:
        entry.selected = value
        if value and entry.status in (Status.DUPLICATE, Status.EXISTS):
            entry.status = Status.READY  # the user wants this one anyway
        self.refresh_import_button()
        self.app.page.update()

    @staticmethod
    def edit(entry: BookEntry, field: str, value: str | None) -> None:
        text = (value or "").strip()
        if field == "series_index":
            try:
                entry.series_index = float(text.replace(",", ".")) if text else None
            except ValueError:
                pass  # the user is still typing; keeps the last valid number
            return
        setattr(entry, field, text)
        if field in ("title", "author"):
            setattr(entry, f"{field}_origin", "manual")

    def refresh_list(self) -> None:
        start = self.page_index * PAGE_SIZE
        self.list_view.controls = [self._row(e) for e in self.entries[start:start + PAGE_SIZE]]
        self.review_body.controls = [self.list_view] if self.entries else [self.empty_text]
        update_pager(self.prev_btn, self.page_label, self.next_btn, self.page_index,
                     page_count(len(self.entries), PAGE_SIZE))
        counts = analysis.summarize(self.entries)
        self.summary_text.value = "  ·  ".join(f"{status.value}: {n}"
                                               for status, n in counts.items())
        self.btn_scan.visible = bool(self.sources)
        self.btn_scan.content = "Analisar de novo" if self.entries else "Analisar"
        self.refresh_import_button()
        self.app.page.update()

    def on_prev(self, _event: Any) -> None:
        self.page_index = max(0, self.page_index - 1)
        self.refresh_list()

    def on_next(self, _event: Any) -> None:
        pages = page_count(len(self.entries), PAGE_SIZE)
        self.page_index = min(pages - 1, self.page_index + 1)
        self.refresh_list()

    # ================================================================== "Como importar"

    def _preview_name(self) -> str | None:
        """Name of a real file, to show how the pattern will be read."""
        if self.entries:
            return self.entries[0].source.stem
        return next((source.stem for source in self.sources if source.is_file()), None)

    def update_pattern_preview(self) -> bool:
        """Shows the result of "Como importar" on the 1st file; False if invalid."""
        preview = self.pattern_preview
        try:
            spec = compile_spec((self.pattern_field.value or "").strip())
        except PatternError as exc:
            preview.value, preview.color = f"Inválido: {exc}", ft.Colors.RED_700
            return False
        name = self._preview_name()
        if name is None:
            preview.value = ("Modo automático: título, autor e volume são deduzidos."
                             if spec is None else
                             "Configuração válida. Adicione PDFs para ver o exemplo.")
            preview.color = ft.Colors.GREY_700
            return True
        described = describe_pattern(name, spec, bool(self.cb_author_first.value))
        preview.value = described.text
        preview.color = ft.Colors.INDIGO_700 if described.ok else ft.Colors.ORANGE_800
        return True

    def on_pattern_change(self, _event: Any) -> None:
        self.update_pattern_preview()
        self.app.page.update()

    async def on_apply_pattern(self, _event: Any) -> None:
        """Re-reads the files with the pattern (manual edits in the list are redone)."""
        if not self.update_pattern_preview():
            self.app.log(self.pattern_preview.value, True)
            return
        self.collect_options()
        self.app.save()
        if self.sources:
            await self.on_scan(None)
        else:
            self.app.page.update()

    async def apply_preset(self, value: str) -> None:
        self.pattern_field.value = value
        if value.endswith("="):  # template to be completed (e.g. "@auth="): does not apply yet
            self.pattern_preview.value = "Complete o valor fixo depois do = e clique em Aplicar."
            self.pattern_preview.color = ft.Colors.GREY_700
            self.app.page.update()
            return
        await self.on_apply_pattern(None)

    def _preset_handler(self, value: str) -> Callable[[Any], Any]:
        async def handler(_event: Any) -> None:  # async def: Flet only awaits async functions
            await self.apply_preset(value)
        return handler

    # ================================================================== sources

    async def on_pick_files(self, _event: Any) -> None:
        try:
            files = await self.app.file_picker.pick_files(
                dialog_title="Escolha os PDFs", allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
        except Exception as exc:
            self.app.log(f"Seletor de arquivos indisponível ({exc}). Cole o caminho no campo.",
                         True)
            return
        if self._add_sources([Path(f.path) for f in files or [] if getattr(f, "path", None)]):
            await self.on_scan(None)

    async def on_pick_folder(self, _event: Any) -> None:
        folder = await self.app.pick_directory("Escolha a pasta com os PDFs")
        if folder and self._add_sources([Path(folder)]):
            await self.on_scan(None)

    async def on_add_typed(self, _event: Any) -> None:
        text = (self.source_input.value or "").strip().strip('"')
        if not text:
            return
        path = Path(text).expanduser()
        if not path.exists():
            self.app.log(f"Caminho não encontrado: {text}", True)
            return
        self.source_input.value = ""
        if self._add_sources([path]):
            await self.on_scan(None)

    def on_clear(self, _event: Any) -> None:
        self.sources.clear()
        self.entries.clear()
        self.page_index = 0
        self._update_sources_label()
        self.refresh_list()
        self.app.save()

    def on_cli_change(self, _event: Any) -> None:
        self.app.settings.cli_path = (self.cli_field.value or "").strip()
        self.refresh_library()
        self.app.page.update()

    # ================================================================== actions

    async def on_scan(self, _event: Any) -> None:
        """Reads the PDFs and adjusts title/author (nothing is written yet)."""
        if not self.sources:
            self.app.log("Escolha ao menos uma pasta ou PDF.", True)
            return
        if not self.update_pattern_preview():
            self.app.log(self.pattern_preview.value, True)
            return
        options = self.collect_options()
        self.app.save()
        try:
            client = self.groq_client()
        except ValueError as exc:
            self.app.log(str(exc), True)
            return
        exclude = self.app.library  # never re-reads the library itself
        try:
            files = await asyncio.to_thread(analysis.find_pdfs, self.sources, options.recursive,
                                            exclude)
            if not files:
                self.app.log("Nenhum PDF encontrado nas origens escolhidas.", True)
                return
            self.app.log(f"{len(files)} PDF(s) encontrados. Lendo e ajustando os metadados…")
            entries = await self.app.run_job(analysis.build_entries, files, options,
                                             label="Analisando")
        except Exception as exc:
            logger.exception("Analysis failed")
            self.app.log(f"Erro na análise: {exc}", True)
            return
        # Identical copies before the AI (does not send the same PDF twice); "same book in
        # different files" afterwards, because it depends on the titles the AI returns.
        duplicates = analysis.mark_identical_files(entries, options)
        self.entries, self.page_index = entries, 0
        ai_summary = await self._fill_with_ai(entries, client, options) if client else ""
        analysis.warn_same_book(entries)
        self.update_pattern_preview()
        self.app.log(f"{len(entries)} PDF(s) analisados, {duplicates} duplicado(s)"
                     f"{'. ' + ai_summary if ai_summary else ''}. Confira os dados e clique em "
                     "Importar para a biblioteca.")
        self.refresh_list()

    async def on_import(self, _event: Any) -> None:
        """Adds the ticked books to the open library."""
        library, cli = self.app.library, self.app.cli()
        if not any(entry.usable for entry in self.entries):
            self.app.log("Nenhum livro marcado para importar.", True)
            return
        if library is None:
            self.app.log("Escolha a biblioteca (item 3) antes de importar.", True)
            return
        if cli is None:
            self.app.log(f"{PRODUCT} não encontrado: instale-o para importar.", True)
            return
        options = self.collect_options()
        self.app.save()
        try:
            report = await self.app.run_job(importer.import_books, self.entries, library,
                                            options, cli, label="Importando")
        except Exception as exc:
            logger.exception("Import failed")
            self.app.log(f"Erro na importação: {exc}", True)
            return
        self.app.log_errors(report.errors)
        self.refresh_list()
        if report.added:
            await self.app.open_library(library)  # the gallery already shows the new books
        self.app.log(report.summary() + (" Veja na aba Galeria." if report.added else ""),
                     error=bool(report.failed))

    async def on_undo_import(self, _event: Any) -> None:
        library, cli = self.app.library, self.app.cli()
        record = importer.latest_import(library) if library else None
        if record is None:
            self.app.log("Não há importação para desfazer nesta biblioteca.", True)
            return
        if cli is None:
            self.app.log(f"{PRODUCT} não encontrado: não dá para desfazer.", True)
            return
        self.app.set_busy(True)
        try:
            count, error = await asyncio.to_thread(importer.undo_import, record, cli)
        finally:
            self.app.set_busy(False)
        if error:
            self.app.log(f"Não foi possível desfazer: {error}", True)
            return
        self.app.log(f"Importação desfeita: {count} livro(s) removidos da biblioteca (ficam na "
                     "lixeira da biblioteca).")
        for entry in self.entries:
            if entry.status is Status.DONE:
                entry.status, entry.selected = Status.READY, True
                entry.notes = [n for n in entry.notes if not n.startswith("na biblioteca")]
        self.refresh_list()
        await self.app.open_library(library)
