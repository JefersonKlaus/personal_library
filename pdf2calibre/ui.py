"""Personal Library: interface Flet em três abas.

1. Importar  - escolhe PDFs, ajusta título/autor automaticamente e adiciona à biblioteca.
2. Galeria   - mostra a biblioteca do Calibre (a mesma que recebe as importações).
3. Exportar  - copia livros da biblioteca para outra pasta, no formato do Calibre.
"""
from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import queue
import threading
from pathlib import Path
from typing import Any, Callable

import flet as ft

from . import APP_NAME, calibre, exporter, library_import, organizer, planner
from .gallery_ui import GalleryView
from .library import LibraryBook, search
from .models import BookEntry, Options, Status
from .naming import (FIELD_LABELS, PATTERN_HELP, PatternError, apply_spec, compile_spec,
                     looks_like_volume)
from .settings import Settings, load_settings, save_settings

logger = logging.getLogger(__name__)

PAGE_SIZE = 40
EXPORT_PAGE_SIZE = 50
MAX_LOG_LINES = 400
LOCKED_STATUSES = (Status.ERROR, Status.DONE, Status.FAILED)
TAB_IMPORT, TAB_GALLERY, TAB_EXPORT = range(3)
PATTERN_PRESETS = [
    ("", "Automático (deduz título, autor e volume)"),
    ("@name - @vol - @auth", "@name - @vol - @auth"),
    ("@name - @vol; @auth=", "@name - @vol; @auth=… (autor fixo)"),
    ("@auth - @name", "@auth - @name"),
    ("@name - @auth", "@name - @auth"),
    ("@auth - @name (@year)", "@auth - @name (@year)"),
]

STATUS_COLORS = {
    Status.READY: ft.Colors.GREEN_700,
    Status.WARNING: ft.Colors.ORANGE_700,
    Status.DUPLICATE: ft.Colors.GREY_600,
    Status.EXISTS: ft.Colors.GREY_600,
    Status.ERROR: ft.Colors.RED_700,
    Status.DONE: ft.Colors.BLUE_700,
    Status.FAILED: ft.Colors.RED_700,
}


def format_size(size: int) -> str:
    """12345678 -> '11,8 MB'."""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            text = f"{value:.0f}" if unit == "B" else f"{value:.1f}".replace(".", ",")
            return f"{text} {unit}"
        value /= 1024
    return f"{size} B"


def section(title: str, *controls: ft.Control, expand: bool = False) -> ft.Container:
    """Bloco com título, usado para agrupar cada etapa da tela."""
    return ft.Container(
        content=ft.Column(controls=[ft.Text(title, weight=ft.FontWeight.BOLD), *controls],
                          spacing=8, expand=expand,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        padding=12, bgcolor=ft.Colors.BLUE_GREY_50, border_radius=8, expand=expand)


def option_grid(*controls: ft.Control) -> ft.ResponsiveRow:
    """Opções lado a lado (Row com wrap empilha as caixas no Flet 1.0)."""
    return ft.ResponsiveRow(
        controls=[ft.Container(content=c, col={"xs": 12, "md": 6, "lg": 3}) for c in controls],
        spacing=4, run_spacing=0)


class PersonalLibraryApp:
    """Monta a janela e liga os botões às funções do pacote."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings: Settings = load_settings()
        self.options: Options = self.settings.get_options()
        self.sources: list[Path] = [Path(p) for p in self.settings.last_sources if Path(p).exists()]
        self.entries: list[BookEntry] = []
        self.page_index = 0
        self.cancel_event = threading.Event()
        self.busy = False
        self.file_picker = ft.FilePicker()
        self.gallery = GalleryView(self)
        # Aba Exportar: seleção e resultado por id de livro da biblioteca.
        self.export_selected: set[int] = set()
        self.export_state: dict[int, tuple[Status, str]] = {}
        self.export_page = 0
        self._known_ids: set[int] = set()
        self._build_shell_controls()
        self._build_import_controls()
        self._build_export_controls()

    # ================================================================== controles

    def _build_shell_controls(self) -> None:
        self.progress = ft.ProgressBar(value=0, width=220, visible=False)
        self.status_text = ft.Text(size=12, expand=True, max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS)
        self.btn_cancel = ft.OutlinedButton("Cancelar", on_click=self.on_cancel, disabled=True,
                                            visible=False)
        self.log_view = ft.ListView(controls=[], spacing=0, auto_scroll=True, expand=True)
        self.log_panel = ft.Container(content=self.log_view, height=150, visible=False,
                                      padding=8, bgcolor=ft.Colors.GREY_100, border_radius=8)
        self.btn_log = ft.TextButton("Registro", icon=ft.Icons.TERMINAL, on_click=self.on_toggle_log)

    def _build_import_controls(self) -> None:
        opts = self.options
        self.source_label = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.source_input = ft.TextField(
            label="Colar caminho (pasta ou PDF)", dense=True, expand=True,
            on_submit=self.on_add_typed)
        self.cb_recursive = ft.Checkbox(label="Incluir subpastas", value=opts.recursive)
        self.cb_dupes = ft.Checkbox(label="Ignorar arquivos idênticos", value=opts.skip_duplicates)
        self.cb_pdf_meta = ft.Checkbox(
            label="Preferir metadados de dentro do PDF", value=opts.prefer_pdf_metadata)
        self.cb_author_first = ft.Checkbox(
            label="Automático: autor vem primeiro", value=opts.author_first,
            tooltip="Só vale sem padrão: 'Autor - Título' em vez de 'Título - Autor'.")
        self.pattern_field = ft.TextField(
            label="Como importar: parâmetros, delimitadores e valores fixos (vazio = automático)",
            hint_text="ex.: @name - @vol - @auth   ou   @name - @vol; @auth=ONE",
            value=opts.filename_pattern, dense=True, expand=True,
            on_change=self.on_pattern_change, on_submit=self.on_apply_pattern)
        self.btn_apply_pattern = ft.FilledTonalButton("Aplicar", icon=ft.Icons.CHECK,
                                                      on_click=self.on_apply_pattern)
        self.pattern_preview = ft.Text(size=12, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        self.btn_scan = ft.OutlinedButton("Analisar de novo", icon=ft.Icons.REFRESH,
                                          on_click=self.on_scan)
        self.summary_text = ft.Text(weight=ft.FontWeight.BOLD)
        self.list_view = ft.ListView(controls=[], spacing=6, expand=True)
        self.import_empty = ft.Text(
            "Adicione PDFs ou uma pasta: título e autor são lidos e ajustados automaticamente. "
            "Confira aqui antes de importar.", size=13, color=ft.Colors.GREY_700)
        self.prev_btn = ft.OutlinedButton("Anterior", on_click=self.on_prev, disabled=True)
        self.next_btn = ft.OutlinedButton("Próxima", on_click=self.on_next, disabled=True)
        self.page_label = ft.Text(size=12)
        # 3. Importar para a biblioteca
        self.import_library_text = ft.Text(size=12, expand=True, max_lines=1,
                                           overflow=ft.TextOverflow.ELLIPSIS)
        self.tags_field = ft.TextField(
            label="Etiquetas para os livros importados (separadas por vírgula)",
            value=", ".join(opts.tags), dense=True, expand=True)
        self.btn_import = ft.FilledButton("Importar para a biblioteca", icon=ft.Icons.LIBRARY_ADD,
                                          on_click=self.on_import, disabled=True)
        self.btn_undo_import = ft.OutlinedButton("Desfazer última importação", icon=ft.Icons.UNDO,
                                                 on_click=self.on_undo_import)
        self.calibredb_field = ft.TextField(
            label="Caminho do calibredb (pasta do Calibre ou o executável)",
            value=self.settings.calibredb, dense=True, on_change=self.on_calibre_change)
        # Aviso quando ainda não há biblioteca (ou ela sumiu): escolher ou criar.
        self._setup_forced = False  # "Trocar biblioteca…" com uma biblioteca válida
        self.setup_title = ft.Text(weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_900)
        self.setup_icon = ft.Icon(ft.Icons.WARNING_AMBER, color=ft.Colors.ORANGE_800)
        self.setup_detected = ft.Column(controls=[], spacing=0)
        self.btn_setup_cancel = ft.TextButton("Cancelar", on_click=self.on_cancel_setup)
        self.library_setup = ft.Container(
            visible=False, padding=12, border_radius=8, bgcolor=ft.Colors.AMBER_50,
            border=ft.Border.all(1, ft.Colors.AMBER_300),
            content=ft.Column(spacing=6, controls=[
                ft.Row(controls=[self.setup_icon, self.setup_title],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Text("Os livros importados vão para uma biblioteca do Calibre. Escolha uma que "
                        "você já usa ou crie uma nova (feche o Calibre antes de criar).", size=12),
                self.setup_detected,
                ft.Row(controls=[
                    ft.FilledTonalButton("Escolher biblioteca existente…",
                                         icon=ft.Icons.FOLDER_OPEN,
                                         on_click=self.on_choose_library),
                    ft.OutlinedButton("Criar biblioteca nova…", icon=ft.Icons.CREATE_NEW_FOLDER,
                                      on_click=self.on_create_library),
                    self.btn_setup_cancel,
                ], spacing=8),
            ]))

    def _build_export_controls(self) -> None:
        settings = self.settings
        self.export_search = ft.TextField(
            hint_text="Filtrar por título, autor, etiqueta…", prefix_icon=ft.Icons.SEARCH,
            dense=True, expand=True, on_change=self.on_export_search)
        self.export_summary = ft.Text(weight=ft.FontWeight.BOLD)
        self.export_list = ft.ListView(controls=[], spacing=2, expand=True)
        self.export_empty = ft.Column(controls=[
            ft.Text("Escolha a biblioteca na aba Galeria para ver os livros que podem ser "
                    "exportados.", size=13, color=ft.Colors.GREY_700),
            ft.OutlinedButton("Abrir a Galeria", icon=ft.Icons.COLLECTIONS_BOOKMARK,
                              on_click=self.on_go_gallery),
        ])
        self.export_prev = ft.OutlinedButton("Anterior", on_click=self.on_export_prev)
        self.export_next = ft.OutlinedButton("Próxima", on_click=self.on_export_next)
        self.export_page_label = ft.Text(size=12)
        self.dest_field = ft.TextField(
            label="Pasta de destino", value=settings.destination, dense=True, expand=True)
        self.cb_folder = ft.Checkbox(
            label="Uma pasta por livro (Autor/Título)", value=settings.export_folder_per_book)
        self.cb_opf = ft.Checkbox(label="Arquivo .opf com os metadados", value=settings.export_opf)
        self.cb_cover = ft.Checkbox(label="Capa (cover.jpg)", value=settings.export_cover)
        self.btn_dry = ft.OutlinedButton("Simular", icon=ft.Icons.VISIBILITY,
                                         on_click=self.on_export_dry_run)
        self.btn_export = ft.FilledButton("Exportar", icon=ft.Icons.IOS_SHARE,
                                          on_click=self.on_export)
        self.btn_undo_export = ft.OutlinedButton("Desfazer última", icon=ft.Icons.UNDO,
                                                 on_click=self.on_undo_export)
        self.action_buttons = [self.btn_scan, self.btn_apply_pattern, self.btn_import,
                               self.btn_undo_import,
                               self.btn_dry, self.btn_export, self.btn_undo_export]

    # ================================================================== montagem

    def build(self) -> None:
        """Registra o seletor de arquivos e coloca as três abas na janela."""
        registry = getattr(self.page, "services", None)
        if registry is None:  # versões antigas do Flet usam overlay
            registry = self.page.overlay
        registry.append(self.file_picker)

        self.tabs = ft.Tabs(
            length=3, selected_index=TAB_IMPORT, expand=True, on_change=self.on_tab_change,
            content=ft.Column(expand=True, controls=[
                ft.TabBar(tabs=[
                    ft.Tab(label="Importar", icon=ft.Icons.UPLOAD_FILE),
                    ft.Tab(label="Galeria", icon=ft.Icons.COLLECTIONS_BOOKMARK),
                    ft.Tab(label="Exportar", icon=ft.Icons.IOS_SHARE),
                ]),
                ft.TabBarView(expand=True, controls=[
                    self._import_tab(), self.gallery.build(), self._export_tab()]),
            ]))
        header = ft.Row(controls=[
            ft.Icon(ft.Icons.AUTO_STORIES, color=ft.Colors.INDIGO_700, size=28),
            ft.Text(APP_NAME, size=22, weight=ft.FontWeight.BOLD),
            ft.Text("importe PDFs para sua biblioteca do Calibre, navegue pela galeria e exporte",
                    size=12, color=ft.Colors.GREY_700),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        status_bar = ft.Row(controls=[
            self.status_text, self.progress, self.btn_cancel, self.btn_log,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)

        self.page.add(ft.Column(controls=[
            header, self.tabs, ft.Divider(height=1), status_bar, self.log_panel,
        ], spacing=6, expand=True))
        self._update_sources_label()
        self.update_pattern_preview()
        self._refresh_list()
        self.refresh_library_info()
        self._refresh_export_list()
        self.page.update()

    def _import_tab(self) -> ft.Control:
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
        review_actions = ft.Row(controls=[self.summary_text, ft.Container(expand=True),
                                          self.btn_scan],
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
        pager = ft.Row(controls=[self.prev_btn, self.page_label, self.next_btn], spacing=12)
        self.review_body = ft.Column(controls=[self.import_empty], expand=True)
        import_row = ft.Row(controls=[self.tags_field, self.btn_import, self.btn_undo_import],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.library_row = ft.Row(controls=[
            ft.Icon(ft.Icons.COLLECTIONS_BOOKMARK, color=ft.Colors.INDIGO_700, size=18),
            self.import_library_text,
            ft.TextButton("Trocar biblioteca…", icon=ft.Icons.SWAP_HORIZ,
                          on_click=self.on_change_library),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6)
        return ft.Container(padding=12, expand=True, content=ft.Column(controls=[
            section("1. Escolha os PDFs", pick_row, self.source_label, options),
            section("2. Confira os dados (ajustados automaticamente)", pattern_row,
                    self.pattern_preview, review_actions, self.review_body, pager, expand=True),
            section("3. Importar para a biblioteca", self.library_setup, import_row,
                    self.library_row, self.calibredb_field),
        ], spacing=10, expand=True))

    def _export_tab(self) -> ft.Control:
        dest_row = ft.Row(controls=[
            self.dest_field,
            ft.OutlinedButton("Escolher…", icon=ft.Icons.FOLDER_OPEN,
                              on_click=self.on_pick_destination),
        ])
        select_row = ft.Row(controls=[
            self.export_search,
            ft.TextButton("Marcar todos", on_click=lambda e: self.on_export_select_all(True)),
            ft.TextButton("Desmarcar todos", on_click=lambda e: self.on_export_select_all(False)),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        pager = ft.Row(controls=[self.export_prev, self.export_page_label, self.export_next],
                       spacing=12)
        self.export_body = ft.Column(controls=[self.export_empty], expand=True)
        left = section("Livros da biblioteca", select_row, self.export_summary,
                       self.export_body, pager, expand=True)
        settings = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10, expand=True, controls=[
            section("Destino", dest_row, ft.Text(
                "Uma pasta comum (pen drive, backup, outro computador). Para colocar livros "
                "numa biblioteca do Calibre use a aba Importar.",
                size=11, color=ft.Colors.GREY_700)),
            section("Formato do Calibre", self.cb_folder, self.cb_opf, self.cb_cover,
                    ft.Text("A pasta exportada pode ser adicionada em qualquer Calibre com "
                            "'Adicionar de pastas e subpastas'.", size=11,
                            color=ft.Colors.GREY_700)),
        ])
        # Botões fora da rolagem: sempre visíveis, mesmo em janelas baixas.
        buttons = ft.Row(controls=[self.btn_dry, self.btn_export, self.btn_undo_export],
                         spacing=8)
        right = ft.Column(width=460, spacing=10, controls=[settings, buttons])
        return ft.Container(padding=12, expand=True, content=ft.Row(
            controls=[left, right], expand=True, spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START))

    # ================================================================== estado

    def _collect_options(self) -> Options:
        tags = [tag.strip() for tag in (self.tags_field.value or "").split(",") if tag.strip()]
        self.options = dataclasses.replace(
            self.options,
            recursive=bool(self.cb_recursive.value),
            skip_duplicates=bool(self.cb_dupes.value),
            prefer_pdf_metadata=bool(self.cb_pdf_meta.value),
            author_first=bool(self.cb_author_first.value),
            filename_pattern=(self.pattern_field.value or "").strip(),
            tags=tags,
            dry_run=False,
        )
        return self.options

    def _export_options(self, dry_run: bool = False) -> exporter.ExportOptions:
        return exporter.ExportOptions(
            folder_per_book=bool(self.cb_folder.value), write_opf=bool(self.cb_opf.value),
            include_cover=bool(self.cb_cover.value), dry_run=dry_run)

    def save(self) -> None:
        self.settings.destination = (self.dest_field.value or "").strip()
        self.settings.library = (self.gallery.library_field.value or "").strip()
        self.settings.calibredb = (self.calibredb_field.value or "").strip()
        self.settings.last_sources = [str(path) for path in self.sources]
        self.settings.export_folder_per_book = bool(self.cb_folder.value)
        self.settings.export_opf = bool(self.cb_opf.value)
        self.settings.export_cover = bool(self.cb_cover.value)
        self.settings.set_options(dataclasses.replace(self.options, dry_run=False))
        save_settings(self.settings)

    def log(self, message: str, error: bool = False) -> None:
        """Registra a mensagem e mostra a última na barra de status."""
        (logger.warning if error else logger.info)(message)
        color = ft.Colors.RED_700 if error else None
        self.log_view.controls.append(ft.Text(message, size=12, color=color, selectable=True))
        del self.log_view.controls[:-MAX_LOG_LINES]
        self.status_text.value = message
        self.status_text.color = color
        if error:
            self.log_panel.visible = True  # erro nunca fica escondido
        self.page.update()

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in self.action_buttons:
            button.disabled = busy
        self.btn_cancel.disabled = not busy
        self.btn_cancel.visible = self.progress.visible = busy
        if not busy:
            self.progress.value = 0
            self._update_import_button()
        self.page.update()

    def _update_sources_label(self) -> None:
        if not self.sources:
            self.source_label.value = "Nenhuma origem escolhida."
        else:
            names = ", ".join(path.name or str(path) for path in self.sources[:4])
            extra = f" e mais {len(self.sources) - 4}" if len(self.sources) > 4 else ""
            self.source_label.value = f"{len(self.sources)} origem(ns): {names}{extra}"

    def library_path(self) -> str:
        return (self.gallery.library_field.value or "").strip()

    def calibredb_path(self) -> Path | None:
        return calibre.find_calibredb((self.calibredb_field.value or "").strip() or None)

    def refresh_library_info(self) -> None:
        """Mostra na aba Importar para qual biblioteca (a da Galeria) os livros vão."""
        library = self.library_path()
        found = self.calibredb_path()
        if not library:
            text, color = "Escolha a biblioteca do Calibre na aba Galeria.", ft.Colors.ORANGE_800
        elif not calibre.is_calibre_library(library):
            text, color = f"{library} não é uma biblioteca do Calibre.", ft.Colors.RED_700
        elif found is None:
            text = "calibredb não encontrado: instale o Calibre ou informe o caminho abaixo."
            color = ft.Colors.ORANGE_800
        else:
            text = f"Os livros vão para {library} · feche o Calibre antes de importar."
            color = ft.Colors.GREY_800
        self.import_library_text.value, self.import_library_text.color = text, color
        self.import_library_text.tooltip = f"calibredb: {found}" if found else None
        self._refresh_library_setup(library)
        # O campo só aparece quando o Calibre não é achado sozinho (caso raro no Windows).
        self.calibredb_field.visible = calibre.find_calibredb() is None
        self._update_import_button()

    def _refresh_library_setup(self, library: str) -> None:
        """Mostra o aviso "escolha ou crie uma biblioteca" quando não há uma válida."""
        valid = bool(library) and calibre.is_calibre_library(library)
        if not library:
            title = "Nenhuma biblioteca do Calibre escolhida ainda."
        elif not Path(library).exists():
            title = f"A biblioteca escolhida não foi encontrada: {library}"
        elif not valid:
            title = f"{library} não é uma biblioteca do Calibre (falta o metadata.db)."
        else:
            title = f"Trocar de biblioteca (atual: {library})"
        show = not valid or self._setup_forced
        self.setup_title.value = title
        # Falta de biblioteca é um aviso; trocar é uma ação normal.
        self.setup_icon.icon = ft.Icons.WARNING_AMBER if not valid else ft.Icons.SWAP_HORIZ
        self.setup_icon.color = ft.Colors.ORANGE_800 if not valid else ft.Colors.INDIGO_700
        self.setup_title.color = ft.Colors.ORANGE_900 if not valid else ft.Colors.INDIGO_900
        self.library_setup.bgcolor = ft.Colors.AMBER_50 if not valid else ft.Colors.INDIGO_50
        self.library_setup.border = ft.Border.all(
            1, ft.Colors.AMBER_300 if not valid else ft.Colors.INDIGO_100)
        self.library_setup.visible = show
        self.library_row.visible = not show
        self.btn_setup_cancel.visible = valid and self._setup_forced
        rows: list[ft.Control] = []
        if show:
            current = os.path.normcase(os.path.abspath(library)) if library else ""
            detected = [path for path in calibre.known_libraries()
                        if os.path.normcase(str(path.absolute())) != current][:4]
            if detected:
                rows.append(ft.Text("Encontradas no seu Calibre:", size=12,
                                    weight=ft.FontWeight.BOLD))
            for path in detected:
                rows.append(ft.Row(controls=[
                    ft.Icon(ft.Icons.COLLECTIONS_BOOKMARK, size=16, color=ft.Colors.INDIGO_700),
                    ft.Text(str(path), size=12, expand=True, selectable=True),
                    ft.TextButton("Usar esta", on_click=self._use_library_handler(path)),
                ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6))
        self.setup_detected.controls = rows

    def _update_import_button(self) -> None:
        ready = any(entry.usable for entry in self.entries)
        library_ok = calibre.is_calibre_library(self.library_path()) if self.library_path() \
            else False
        self.btn_import.disabled = self.busy or not (
            ready and library_ok and self.calibredb_path() is not None)

    def _add_sources(self, paths: list[Path]) -> bool:
        """Adiciona origens; True se vale analisar (algo novo ou nada analisado ainda)."""
        added = False
        for path in paths:
            if path not in self.sources:
                self.sources.append(path)
                added = True
        self._update_sources_label()
        self.save()
        self.page.update()
        return bool(paths) and (added or not self.entries)

    # ================================================================== biblioteca: escolher ou criar

    def _use_library_handler(self, path: Path) -> Callable[[Any], Any]:
        async def handler(_event: Any) -> None:  # async def: o Flet só espera funções async
            await self.use_library(path)
        return handler

    async def use_library(self, path: Path) -> None:
        """Passa a usar esta biblioteca (na Importação, na Galeria e na Exportação)."""
        self._setup_forced = False
        await self.gallery.load(str(path))
        self.refresh_library_info()
        if self.gallery.library is not None:
            self.log(f"Biblioteca: {path}. Os livros importados vão para ela.")

    async def on_change_library(self, _event: Any) -> None:
        self._setup_forced = True
        self.refresh_library_info()
        self.page.update()

    def on_cancel_setup(self, _event: Any) -> None:
        self._setup_forced = False
        self.refresh_library_info()
        self.page.update()

    async def on_choose_library(self, _event: Any) -> None:
        folder = await self.pick_directory(
            "Escolha a pasta da biblioteca do Calibre (a que tem metadata.db)")
        if not folder:
            return
        found = calibre.find_library_in(folder)
        if found is None:
            self.log(f"{folder} não é uma biblioteca do Calibre (não tem metadata.db). "
                     "Para começar uma nova, use Criar biblioteca nova.", True)
            return
        await self.use_library(found)

    async def on_create_library(self, _event: Any) -> None:
        """Pergunta onde criar, confirma e cria uma biblioteca vazia com o calibredb."""
        tool = self.calibredb_path()
        if tool is None:
            self.log("Para criar uma biblioteca é preciso ter o Calibre instalado (calibredb).",
                     True)
            return
        parent = await self.pick_directory("Escolha onde criar a biblioteca nova")
        if not parent:
            return
        target = calibre.new_library_path(Path(parent))

        def close(_e: Any = None) -> None:
            self.page.pop_dialog()

        async def create(_e: Any) -> None:
            self.page.pop_dialog()
            await self.create_library_at(target, tool)

        self.page.show_dialog(ft.AlertDialog(
            title=ft.Text("Criar biblioteca do Calibre"),
            content=ft.Column(tight=True, spacing=8, width=520, controls=[
                ft.Text("A biblioteca nova (vazia) será criada em:"),
                ft.Text(str(target), weight=ft.FontWeight.BOLD, selectable=True),
                ft.Text("Feche o Calibre antes de continuar. Depois, para abri-la no Calibre: "
                        "botão Biblioteca > Alternar/criar biblioteca > escolha esta pasta.",
                        size=12, color=ft.Colors.GREY_700),
            ]),
            actions=[ft.TextButton("Cancelar", on_click=close),
                     ft.FilledButton("Criar biblioteca", icon=ft.Icons.CREATE_NEW_FOLDER,
                                     on_click=create)]))

    async def create_library_at(self, target: Path, tool: Path) -> None:
        self._set_busy(True)
        self.status_text.value = f"Criando a biblioteca em {target}…"
        self.page.update()
        try:
            ok, error = await asyncio.to_thread(calibre.create_library, tool, target)
        finally:
            self._set_busy(False)
        if not ok:
            self.log(f"Não foi possível criar a biblioteca: {error}", True)
            return
        await self.use_library(target)
        self.log(f"Biblioteca criada em {target}. Para vê-la no Calibre: botão Biblioteca > "
                 "Alternar/criar biblioteca.")

    # ================================================================== aba Importar: lista

    def _row(self, entry: BookEntry) -> ft.Control:
        checkbox = ft.Checkbox(
            value=entry.selected, disabled=entry.status in LOCKED_STATUSES,
            on_change=lambda e, item=entry: self._toggle(item, bool(e.control.value)))
        title = ft.TextField(
            label="Título", value=entry.title, dense=True, expand=3,
            read_only=entry.status is Status.DONE,
            on_change=lambda e, item=entry: self._edit(item, "title", e.control.value))
        author = ft.TextField(
            label="Autor(es), separe com &", value=entry.author, dense=True, expand=2,
            read_only=entry.status is Status.DONE,
            on_change=lambda e, item=entry: self._edit(item, "author", e.control.value))
        series = ft.TextField(
            label="Série", value=entry.series, dense=True, expand=2,
            read_only=entry.status is Status.DONE,
            on_change=lambda e, item=entry: self._edit(item, "series", e.control.value))
        volume = ft.TextField(
            label="Vol.", dense=True, width=72, read_only=entry.status is Status.DONE,
            value=f"{entry.series_index:g}" if entry.series_index is not None else "",
            on_change=lambda e, item=entry: self._edit(item, "series_index", e.control.value))
        status = ft.Text(entry.status.value, color=STATUS_COLORS[entry.status],
                         weight=ft.FontWeight.BOLD, width=84)
        detail = f"{entry.source.name} · {entry.pages} pág. · {format_size(entry.size)}"
        if entry.notes:
            detail += " · " + "; ".join(entry.notes)
        return ft.Column(controls=[
            ft.Row(controls=[checkbox, title, author, series, volume, status],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Text(detail, size=11, color=ft.Colors.GREY_600),
        ], spacing=0)

    def _toggle(self, entry: BookEntry, value: bool) -> None:
        entry.selected = value
        if value and entry.status in (Status.DUPLICATE, Status.EXISTS):
            entry.status = Status.READY  # o usuário quer este mesmo assim
        self._update_import_button()
        self.page.update()

    def _edit(self, entry: BookEntry, field: str, value: str | None) -> None:
        text = (value or "").strip()
        if field == "series_index":
            try:
                entry.series_index = float(text.replace(",", ".")) if text else None
            except ValueError:
                pass  # o usuário ainda está digitando; mantém o último número válido
            return
        setattr(entry, field, text)
        if field in ("title", "author"):
            setattr(entry, f"{field}_origin", "manual")

    def _page_count(self) -> int:
        return max(1, -(-len(self.entries) // PAGE_SIZE))

    def _refresh_list(self) -> None:
        start = self.page_index * PAGE_SIZE
        self.list_view.controls = [self._row(item) for item in self.entries[start:start + PAGE_SIZE]]
        self.review_body.controls = [self.list_view] if self.entries else [self.import_empty]
        pages = self._page_count()
        self.page_label.value = f"Página {self.page_index + 1} de {pages}"
        self.prev_btn.disabled = self.page_index == 0
        self.next_btn.disabled = self.page_index >= pages - 1
        for control in (self.prev_btn, self.page_label, self.next_btn):
            control.visible = pages > 1
        counts = planner.summarize(self.entries)
        self.summary_text.value = (
            "  ·  ".join(f"{status.value}: {n}" for status, n in counts.items())
            if self.entries else "")
        self.btn_scan.visible = bool(self.sources)
        self.btn_scan.content = "Analisar de novo" if self.entries else "Analisar"
        self._update_import_button()
        self.page.update()

    def on_prev(self, _event: Any) -> None:
        self.page_index = max(0, self.page_index - 1)
        self._refresh_list()

    def on_next(self, _event: Any) -> None:
        self.page_index = min(self._page_count() - 1, self.page_index + 1)
        self._refresh_list()

    # ================================================================== aba Importar: padrão do nome

    def _preview_name(self) -> str | None:
        """Nome de um arquivo real para mostrar como o padrão será lido."""
        if self.entries:
            return self.entries[0].source.stem
        for source in self.sources:
            if source.is_file():
                return source.stem
        return None

    def update_pattern_preview(self) -> bool:
        """Mostra o resultado de "Como importar" no 1º arquivo; False se inválido."""
        text = (self.pattern_field.value or "").strip()
        try:
            spec = compile_spec(text)
        except PatternError as exc:
            self.pattern_preview.value = f"Inválido: {exc}"
            self.pattern_preview.color = ft.Colors.RED_700
            return False
        name = self._preview_name()
        if name is None:
            self.pattern_preview.value = ("Modo automático: título, autor e volume são deduzidos."
                                          if spec is None else
                                          "Configuração válida. Adicione PDFs para ver o exemplo.")
            self.pattern_preview.color = ft.Colors.GREY_700
            return True
        parsed, matched = apply_spec(name, spec, bool(self.cb_author_first.value))
        fixed = spec.fixed if spec is not None else {}

        def mark(field: str, value: str = "") -> str:
            if looks_like_volume(value):
                return " (parece um volume: use @vol)"
            return " (fixo)" if field in fixed else ""

        parts = [f"Título: {parsed.title}{mark('title', parsed.title)}",
                 f"Autor: {parsed.author or '—'}{mark('author', parsed.author)}"]
        if parsed.series_index is not None:
            parts.append(f"Vol.: {parsed.series_index:g}{mark('volume')}")
        if parsed.series:
            origin = " (de @name: o Calibre só guarda o volume dentro de uma série)" \
                if parsed.series_from_name else mark("series")
            parts.append(f"Série: {parsed.series}{origin}")
        for field, value in (("year", parsed.year), ("publisher", parsed.publisher),
                             ("language", parsed.language), ("tags", ", ".join(parsed.tags))):
            if value:
                parts.append(f"{FIELD_LABELS[field]}: {value}{mark(field)}")
        prefix = f"«{name}» → " if matched else \
            f"«{name}» não segue o padrão; no automático → "
        self.pattern_preview.value = prefix + " · ".join(parts)
        suspicious = looks_like_volume(parsed.author) or looks_like_volume(parsed.title)
        self.pattern_preview.color = ft.Colors.INDIGO_700 if matched and not suspicious \
            else ft.Colors.ORANGE_800
        return True

    def on_pattern_change(self, _event: Any) -> None:
        self.update_pattern_preview()
        self.page.update()

    async def on_apply_pattern(self, _event: Any) -> None:
        """Relê os arquivos com o padrão (as edições manuais da lista são refeitas)."""
        if not self.update_pattern_preview():
            self.log(self.pattern_preview.value, True)
            return
        self._collect_options()
        self.save()
        if self.sources:
            await self.on_scan(None)
        else:
            self.page.update()

    async def on_pattern_preset(self, value: str) -> None:
        self.pattern_field.value = value
        if value.endswith("="):  # modelo para completar (ex.: "@auth="): não aplica ainda
            self.update_pattern_preview()
            self.pattern_preview.value = "Complete o valor fixo depois do = e clique em Aplicar."
            self.pattern_preview.color = ft.Colors.GREY_700
            self.page.update()
            return
        await self.on_apply_pattern(None)

    def _preset_handler(self, value: str) -> Callable[[Any], Any]:
        # Precisa ser "async def": o Flet só espera (await) funções assíncronas;
        # um lambda que devolve a corrotina seria chamado e ignorado.
        async def handler(_event: Any) -> None:
            await self.on_pattern_preset(value)
        return handler

    # ================================================================== aba Exportar: lista

    def on_library_loaded(self, books: list[LibraryBook], changed: bool) -> None:
        """Chamado pela Galeria: mantém a seleção e marca os livros novos."""
        ids = {book.id for book in books}
        if changed:
            self.export_selected, self.export_state = set(ids), {}
        else:
            self.export_selected = (self.export_selected & ids) | (ids - self._known_ids)
        self._known_ids = ids
        self.export_page = 0
        self._refresh_export_list()

    def export_view(self) -> list[LibraryBook]:
        """Livros da biblioteca que aparecem na lista (respeitando o filtro)."""
        return search(self.gallery.books, self.export_search.value or "") \
            if self.gallery.library is not None else []

    def _export_row(self, book: LibraryBook) -> ft.Control:
        status, message = self.export_state.get(book.id, (None, ""))
        detail = ", ".join(sorted(book.formats)) or "sem arquivo"
        if message:
            detail += f" · {message}"
        controls: list[ft.Control] = [
            ft.Checkbox(value=book.id in self.export_selected,
                        on_change=lambda e, item=book: self._export_toggle(
                            item, bool(e.control.value))),
            ft.Column(controls=[
                ft.Text(f"{book.title} — {book.authors_text}", size=13, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(detail, size=11, color=ft.Colors.GREY_600, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=0, expand=True),
        ]
        if status is not None:
            controls.append(ft.Text(status.value, color=STATUS_COLORS[status],
                                    weight=ft.FontWeight.BOLD, size=12, width=80))
        return ft.Row(controls=controls, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _export_toggle(self, book: LibraryBook, value: bool) -> None:
        (self.export_selected.add if value else self.export_selected.discard)(book.id)
        self._refresh_export_summary()
        self.page.update()

    def _refresh_export_summary(self) -> None:
        if self.gallery.library is None:
            self.export_summary.value = ""
            return
        total = len(self.gallery.books)
        view = self.export_view()
        text = f"{len(self.export_selected)} de {total} livro(s) marcados para exportar"
        if len(view) != total:
            text += f" · {len(view)} no filtro"
        done = sum(1 for status, _m in self.export_state.values() if status is Status.DONE)
        if done:
            text += f" · {done} exportado(s)"
        self.export_summary.value = text

    def _refresh_export_list(self) -> None:
        if self.gallery.library is None:
            self.export_body.controls = [self.export_empty]
            for control in (self.export_prev, self.export_page_label, self.export_next):
                control.visible = False
            self._refresh_export_summary()
            self.page.update()
            return
        view = self.export_view()
        pages = max(1, -(-len(view) // EXPORT_PAGE_SIZE))
        self.export_page = min(self.export_page, pages - 1)
        start = self.export_page * EXPORT_PAGE_SIZE
        self.export_list.controls = [self._export_row(book)
                                     for book in view[start:start + EXPORT_PAGE_SIZE]]
        self.export_body.controls = [self.export_list]
        self.export_page_label.value = f"Página {self.export_page + 1} de {pages}"
        self.export_prev.disabled = self.export_page == 0
        self.export_next.disabled = self.export_page >= pages - 1
        for control in (self.export_prev, self.export_page_label, self.export_next):
            control.visible = pages > 1
        self._refresh_export_summary()
        self.page.update()

    def on_export_search(self, _event: Any) -> None:
        self.export_page = 0
        self._refresh_export_list()

    def on_export_select_all(self, value: bool) -> None:
        """Marca/desmarca os livros do filtro atual (ou todos, sem filtro)."""
        ids = {book.id for book in self.export_view()}
        self.export_selected = self.export_selected | ids if value else self.export_selected - ids
        self._refresh_export_list()

    def on_export_prev(self, _event: Any) -> None:
        self.export_page = max(0, self.export_page - 1)
        self._refresh_export_list()

    def on_export_next(self, _event: Any) -> None:
        self.export_page += 1
        self._refresh_export_list()

    # ================================================================== eventos gerais

    async def on_tab_change(self, _event: Any) -> None:
        index = self.tabs.selected_index
        if index in (TAB_GALLERY, TAB_EXPORT) and self.gallery.library is None \
                and self.library_path():
            await self.gallery.load(self.library_path())
        if index == TAB_EXPORT:
            self._refresh_export_list()
        elif index == TAB_IMPORT:
            self.refresh_library_info()
            self.page.update()

    async def on_go_gallery(self, _event: Any) -> None:
        self.tabs.selected_index = TAB_GALLERY
        await self.on_tab_change(None)
        self.page.update()

    def on_toggle_log(self, _event: Any) -> None:
        self.log_panel.visible = not self.log_panel.visible
        self.page.update()

    def on_cancel(self, _event: Any) -> None:
        self.cancel_event.set()
        self.status_text.value = "Cancelando…"
        self.page.update()

    def on_calibre_change(self, _event: Any) -> None:
        self.refresh_library_info()
        self.page.update()

    # ================================================================== origem e destino

    async def on_pick_files(self, _event: Any) -> None:
        try:
            files = await self.file_picker.pick_files(
                dialog_title="Escolha os PDFs", allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=["pdf"])
        except Exception as exc:
            self.log(f"Seletor de arquivos indisponível ({exc}). Cole o caminho no campo.", True)
            return
        paths = [Path(f.path) for f in files or [] if getattr(f, "path", None)]
        if self._add_sources(paths):
            await self.on_scan(None)

    async def on_pick_folder(self, _event: Any) -> None:
        folder = await self.pick_directory("Escolha a pasta com os PDFs")
        if folder and self._add_sources([Path(folder)]):
            await self.on_scan(None)

    async def on_pick_destination(self, _event: Any) -> None:
        folder = await self.pick_directory("Escolha a pasta de destino")
        if folder:
            self.dest_field.value = folder
            self.save()
            self.page.update()

    async def pick_directory(self, title: str) -> str | None:
        try:
            return await self.file_picker.get_directory_path(dialog_title=title)
        except Exception as exc:
            self.log(f"Seletor de pastas indisponível ({exc}). Cole o caminho no campo.", True)
            return None

    async def on_add_typed(self, _event: Any) -> None:
        text = (self.source_input.value or "").strip().strip('"')
        if not text:
            return
        path = Path(text).expanduser()
        if not path.exists():
            self.log(f"Caminho não encontrado: {text}", True)
            return
        self.source_input.value = ""
        if self._add_sources([path]):
            await self.on_scan(None)

    def on_clear(self, _event: Any) -> None:
        self.sources.clear()
        self.entries.clear()
        self.page_index = 0
        self._update_sources_label()
        self._refresh_list()
        self.save()

    # ================================================================== execução

    def _drain(self, updates: "queue.Queue[tuple[int, int, str]]", label: str) -> None:
        latest = None
        while True:
            try:
                latest = updates.get_nowait()
            except queue.Empty:
                break
        if latest is None:
            return
        done, total, message = latest
        self.progress.value = done / total if total else None
        self.status_text.value = f"{label}: {done}/{total} — {message}"
        self.status_text.color = None
        self.page.update()

    async def _run_job(self, func: Callable[..., Any], *args: Any, label: str,
                       cancellable: bool = True) -> Any:
        """Roda `func` em outra thread mostrando o progresso, sem travar a janela."""
        updates: "queue.Queue[tuple[int, int, str]]" = queue.Queue()
        kwargs: dict[str, Any] = {"progress": lambda d, t, m: updates.put((d, t, m))}
        if cancellable:
            kwargs["cancel"] = self.cancel_event
        self.cancel_event.clear()
        self._set_busy(True)
        task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        try:
            while not task.done():
                self._drain(updates, label)
                await asyncio.sleep(0.1)
            self._drain(updates, label)
            return task.result()
        finally:
            self._set_busy(False)

    async def on_scan(self, _event: Any) -> None:
        """Lê os PDFs e ajusta título/autor (ainda não grava nada)."""
        if not self.sources:
            self.log("Escolha ao menos uma pasta ou PDF.", True)
            return
        if not self.update_pattern_preview():
            self.log(self.pattern_preview.value, True)
            return
        options = self._collect_options()
        self.save()
        library = self.library_path()
        exclude = Path(library) if library else None  # nunca reimporta a própria biblioteca
        try:
            files = await asyncio.to_thread(planner.find_pdfs, self.sources, options.recursive,
                                            exclude)
            if not files:
                self.log("Nenhum PDF encontrado nas origens escolhidas.", True)
                return
            self.log(f"{len(files)} PDF(s) encontrados. Lendo e ajustando os metadados…")
            entries = await self._run_job(
                planner.build_entries, files, options, label="Analisando")
        except Exception as exc:
            logger.exception("Falha na análise")
            self.log(f"Erro na análise: {exc}", True)
            return
        duplicates = planner.mark_duplicates(entries, options)
        self.entries, self.page_index = entries, 0
        self.update_pattern_preview()
        self.log(f"{len(entries)} PDF(s) analisados, {duplicates} duplicado(s). Confira título e "
                 "autor e clique em Importar para a biblioteca.")
        self._refresh_list()

    async def on_import(self, _event: Any) -> None:
        """Adiciona os livros marcados à biblioteca da Galeria (via calibredb)."""
        library = self.library_path()
        tool = self.calibredb_path()
        if not any(entry.usable for entry in self.entries):
            self.log("Nenhum livro marcado para importar.", True)
            return
        if not calibre.is_calibre_library(library):
            self.log("Escolha uma biblioteca do Calibre na aba Galeria antes de importar.", True)
            return
        if tool is None:
            self.log("calibredb não encontrado: instale o Calibre para importar.", True)
            return
        options = self._collect_options()
        self.save()
        try:
            report = await self._run_job(
                library_import.import_to_library, self.entries, Path(library), options, tool,
                label="Importando")
        except Exception as exc:
            logger.exception("Falha na importação")
            self.log(f"Erro na importação: {exc}", True)
            return
        for error in report.errors[:20]:
            self.log(f"  ✗ {error}", True)
        self._refresh_list()
        if report.added:
            await self.gallery.load(library)  # a galeria já mostra os livros novos
        self.log(report.summary() + (" Veja na aba Galeria." if report.added else ""),
                 error=bool(report.failed))

    async def on_undo_import(self, _event: Any) -> None:
        library, tool = self.library_path(), self.calibredb_path()
        record = library_import.latest_import(Path(library)) if library else None
        if record is None:
            self.log("Não há importação para desfazer nesta biblioteca.", True)
            return
        if tool is None:
            self.log("calibredb não encontrado: não dá para desfazer.", True)
            return
        self._set_busy(True)
        try:
            count, error = await asyncio.to_thread(library_import.undo_import, record, tool)
        finally:
            self._set_busy(False)
        if error:
            self.log(f"Não foi possível desfazer: {error}", True)
            return
        self.log(f"Importação desfeita: {count} livro(s) removidos da biblioteca "
                 "(ficam na lixeira do Calibre).")
        for entry in self.entries:
            if entry.status is Status.DONE:
                entry.status, entry.selected = Status.READY, True
                entry.notes = [n for n in entry.notes if not n.startswith("na biblioteca")]
        self._refresh_list()
        await self.gallery.load(library)

    async def on_export_dry_run(self, _event: Any) -> None:
        await self._export(dry_run=True)

    async def on_export(self, _event: Any) -> None:
        await self._export(dry_run=False)

    async def _export(self, dry_run: bool) -> None:
        if self.gallery.library is None:
            self.log("Escolha a biblioteca na aba Galeria antes de exportar.", True)
            return
        books = [book for book in self.gallery.books if book.id in self.export_selected]
        if not books:
            self.log("Marque ao menos um livro para exportar.", True)
            return
        dest = (self.dest_field.value or "").strip()
        if not dest:
            self.log("Informe a pasta de destino.", True)
            return
        self.save()
        try:
            report, items = await self._run_job(
                exporter.export_books, books, self.gallery.library, Path(dest),
                self._export_options(dry_run), label="Simulando" if dry_run else "Exportando")
        except Exception as exc:
            logger.exception("Falha ao exportar")
            self.log(f"Erro ao exportar: {exc}", True)
            return
        for item in items:
            if dry_run and item.status is Status.READY:
                target = item.target.relative_to(dest) if item.target else ""
                self.export_state[item.book.id] = (Status.READY, f"iria para {target}")
            else:
                self.export_state[item.book.id] = (item.status, item.message)
        for error in report.errors[:20]:
            self.log(f"  ✗ {error}", True)
        if report.manifest:
            self.log(f"Registro para desfazer: {report.manifest}")
        if dry_run:
            message = f"Simulação: {report.done} livro(s) seriam exportados para {dest}"
        else:
            message = f"{report.done} livro(s) exportados para {dest}"
        if report.skipped:
            message += f" · {report.skipped} já estavam lá ou sem arquivo"
        if report.failed:
            message += f" · {report.failed} com erro"
        self.log(message + ".", error=bool(report.failed))
        self._refresh_export_list()

    async def on_undo_export(self, _event: Any) -> None:
        dest = (self.dest_field.value or "").strip()
        manifest = organizer.latest_manifest(Path(dest)) if dest else None
        if manifest is None:
            self.log("Não há exportação para desfazer neste destino.", True)
            return
        try:
            report = await self._run_job(
                organizer.undo, manifest, label="Desfazendo", cancellable=False)
        except Exception as exc:
            logger.exception("Falha ao desfazer")
            self.log(f"Erro ao desfazer: {exc}", True)
            return
        for error in report.errors[:20]:
            self.log(f"  ✗ {error}", True)
        self.log(f"Exportação desfeita: {report.done} de {report.total} livros.",
                 error=bool(report.failed))
        self.export_state.clear()
        self._refresh_export_list()


async def main(page: ft.Page) -> None:
    """Ponto de entrada passado para `ft.run`."""
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
    page.padding = 12
    try:
        page.window.width = 1200
        page.window.height = 860
        page.window.min_width = 900
        page.window.min_height = 640
        page.window.maximized = True  # mais linhas visíveis na revisão e na galeria
    except Exception:  # janela não configurável (web/mobile): sem problema
        logger.debug("window não configurável", exc_info=True)
    PersonalLibraryApp(page).build()
