"""Janela principal: monta as abas e oferece os serviços que elas compartilham.

Serviços: registro/barra de status, tarefas em segundo plano com progresso,
seletor de pastas, preferências e a biblioteca aberta (a mesma nas três abas).
"""
from __future__ import annotations

import asyncio
import logging
import queue
import threading
from pathlib import Path
from typing import Any, Callable

import flet as ft

from .. import APP_NAME
from ..library.cli import LibraryCli
from ..library.database import LibraryBook, LibraryError, load_library
from ..settings import Settings, load_settings, save_settings
from .export_tab import ExportTab
from .gallery_tab import GalleryTab
from .import_tab import ImportTab
from .library_picker import LibraryPicker
from .widgets import TAB_IMPORT

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 400


class PersonalLibraryApp:
    """Monta a janela e coordena as abas."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings: Settings = load_settings()
        self.file_picker = ft.FilePicker()
        self.cancel_event = threading.Event()
        self.busy = False
        self._action_buttons: list[ft.Control] = []
        # A biblioteca aberta (None se a escolhida não existe ou não é válida).
        self.library: Path | None = None
        self.books: list[LibraryBook] = []
        self._build_status_bar()
        self.library_picker = LibraryPicker(self)
        self.import_tab = ImportTab(self)
        self.gallery = GalleryTab(self)
        self.export_tab = ExportTab(self)

    # ================================================================== montagem

    def _build_status_bar(self) -> None:
        self.progress = ft.ProgressBar(value=0, width=220, visible=False)
        self.status_text = ft.Text(size=12, expand=True, max_lines=1,
                                   overflow=ft.TextOverflow.ELLIPSIS)
        self.btn_cancel = ft.OutlinedButton("Cancelar", on_click=self.on_cancel, disabled=True,
                                            visible=False)
        self.log_view = ft.ListView(controls=[], spacing=0, auto_scroll=True, expand=True)
        self.log_panel = ft.Container(content=self.log_view, height=150, visible=False,
                                      padding=8, bgcolor=ft.Colors.GREY_100, border_radius=8)
        self.btn_log = ft.TextButton("Registro", icon=ft.Icons.TERMINAL,
                                     on_click=self.on_toggle_log)

    def build(self) -> None:
        """Registra o seletor de arquivos e coloca as três abas na janela."""
        registry = getattr(self.page, "services", None)
        if registry is None:  # versões antigas do Flet usam overlay
            registry = self.page.overlay
        registry.append(self.file_picker)
        if getattr(self.page, "web", False):
            # No navegador, o botão direito mostraria o menu do navegador, não o da galeria.
            self.browser_menu = ft.BrowserContextMenu()
            registry.append(self.browser_menu)
        self.tabs = ft.Tabs(
            length=3, selected_index=TAB_IMPORT, expand=True,
            content=ft.Column(expand=True, controls=[
                ft.TabBar(tabs=[
                    ft.Tab(label="Importar", icon=ft.Icons.UPLOAD_FILE),
                    ft.Tab(label="Galeria", icon=ft.Icons.COLLECTIONS_BOOKMARK),
                    ft.Tab(label="Exportar", icon=ft.Icons.IOS_SHARE),
                ]),
                ft.TabBarView(expand=True, controls=[
                    self.import_tab.build(), self.gallery.build(), self.export_tab.build()]),
            ]))
        header = ft.Row(controls=[
            ft.Icon(ft.Icons.AUTO_STORIES, color=ft.Colors.INDIGO_700, size=28),
            ft.Text(APP_NAME, size=22, weight=ft.FontWeight.BOLD),
            ft.Text("importe PDFs para a sua biblioteca, navegue pela galeria e exporte",
                    size=12, color=ft.Colors.GREY_700),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        status_bar = ft.Row(controls=[self.status_text, self.progress, self.btn_cancel,
                                      self.btn_log],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.page.add(ft.Column(controls=[header, self.tabs, ft.Divider(height=1), status_bar,
                                          self.log_panel], spacing=6, expand=True))
        self.library_picker.refresh()
        self.import_tab.refresh()
        self.export_tab.refresh()
        self.page.update()

    async def use_app_context_menus(self) -> None:
        """Só na versão web: desliga o menu do navegador (senão o "Abrir" da galeria não
        aparece com o botão direito). No app de desktop não há o que fazer."""
        menu = getattr(self, "browser_menu", None)
        if menu is None:
            return
        try:
            await menu.disable()
        except Exception:
            logger.debug("não foi possível desligar o menu do navegador", exc_info=True)

    async def go_to_tab(self, index: int) -> None:
        self.tabs.selected_index = index
        self.page.update()

    # ================================================================== biblioteca aberta

    async def open_library(self, path: str | Path | None) -> bool:
        """Passa a usar a biblioteca em `path` (nas três abas). False se não for válida."""
        folder = str(path or "").strip().strip('"')
        previous = self.library
        self.settings.library = folder
        self.save()
        error = ""
        if not folder:
            self.library, self.books = None, []
        else:
            self.gallery.show_loading()
            try:
                books = await asyncio.to_thread(load_library, Path(folder))
            except LibraryError as exc:
                self.library, self.books, error = None, [], str(exc)
            else:
                self.library, self.books = Path(folder), books
                self.log(f"Biblioteca: {len(books)} livro(s) em {folder}.")
        changed = previous != self.library
        self.library_picker.refresh()
        self.import_tab.refresh_library()
        self.export_tab.on_library_changed(changed)
        await self.gallery.on_library_changed(error)
        return self.library is not None

    def cli(self) -> LibraryCli | None:
        """A ferramenta que altera a biblioteca (None se não estiver instalada)."""
        return LibraryCli.find(self.settings.cli_path or None)

    # ================================================================== serviços

    def save(self) -> None:
        """Cada aba guarda os próprios campos nas preferências; depois grava o arquivo."""
        for tab in (self.import_tab, self.export_tab, self.gallery):
            tab.store(self.settings)
        save_settings(self.settings)

    def log(self, message: str, error: bool = False) -> None:
        """Registra a mensagem e mostra a última na barra de status."""
        (logger.warning if error else logger.info)(message)
        color = ft.Colors.RED_700 if error else None
        self.log_view.controls.append(ft.Text(message, size=12, color=color, selectable=True))
        del self.log_view.controls[:-MAX_LOG_LINES]
        self.status_text.value, self.status_text.color = message, color
        if error:
            self.log_panel.visible = True  # erro nunca fica escondido
        self.page.update()

    def register_actions(self, *buttons: ft.Control) -> None:
        """Botões que ficam desativados enquanto uma tarefa está rodando."""
        self._action_buttons.extend(buttons)

    def set_busy(self, busy: bool) -> None:
        self.busy = busy
        for button in self._action_buttons:
            button.disabled = busy
        self.btn_cancel.disabled = not busy
        self.btn_cancel.visible = self.progress.visible = busy
        if not busy:
            self.progress.value = 0
            self.import_tab.refresh_import_button()
        self.page.update()

    def show_progress(self, done: int, total: int, message: str, label: str) -> None:
        self.progress.value = done / total if total else None
        self.status_text.value, self.status_text.color = f"{label}: {done}/{total} — {message}", None
        self.page.update()

    async def run_job(self, func: Callable[..., Any], *args: Any, label: str,
                      cancellable: bool = True) -> Any:
        """Roda `func` em outra thread mostrando o progresso, sem travar a janela."""
        updates: "queue.Queue[tuple[int, int, str]]" = queue.Queue()
        kwargs: dict[str, Any] = {"progress": lambda d, t, m: updates.put((d, t, m))}
        if cancellable:
            kwargs["cancel"] = self.cancel_event
        self.cancel_event.clear()
        self.set_busy(True)
        task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
        try:
            while not task.done():
                self._drain(updates, label)
                await asyncio.sleep(0.1)
            self._drain(updates, label)
            return task.result()
        finally:
            self.set_busy(False)

    def _drain(self, updates: "queue.Queue[tuple[int, int, str]]", label: str) -> None:
        latest = None
        while not updates.empty():
            latest = updates.get_nowait()
        if latest is not None:
            self.show_progress(*latest, label)

    async def pick_directory(self, title: str) -> str | None:
        try:
            return await self.file_picker.get_directory_path(dialog_title=title)
        except Exception as exc:
            self.log(f"Seletor de pastas indisponível ({exc}). Cole o caminho no campo.", True)
            return None

    # ================================================================== eventos

    def on_toggle_log(self, _event: Any) -> None:
        self.log_panel.visible = not self.log_panel.visible
        self.page.update()

    def on_cancel(self, _event: Any) -> None:
        self.cancel_event.set()
        self.status_text.value = "Cancelando…"
        self.page.update()


async def main(page: ft.Page) -> None:
    """Ponto de entrada passado para `ft.run`."""
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
    page.padding = 12
    try:
        page.window.width, page.window.height = 1200, 860
        page.window.min_width, page.window.min_height = 900, 640
        page.window.maximized = True  # mais linhas visíveis na revisão e na galeria
    except Exception:  # janela não configurável (web/mobile): sem problema
        logger.debug("window não configurável", exc_info=True)
    app = PersonalLibraryApp(page)
    app.build()
    await app.use_app_context_menus()
    if app.settings.library:
        await app.open_library(app.settings.library)
