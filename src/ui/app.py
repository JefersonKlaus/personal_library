"""Main window: builds the tabs and offers the services they share.

Services: log/status bar, background jobs with progress, folder picker, settings
and the open library (the same one in the three tabs).
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
from ..core.settings import Settings, load_settings, save_settings
from ..library.cli import LibraryCli
from ..library.database import LibraryBook, LibraryError, load_library
from .book_opener import BookOpener
from .export_tab import ExportTab
from .gallery_tab import GalleryTab
from .import_tab import ImportTab
from .keyboard import ModifierKeys
from .library_picker import LibraryPicker
from .widgets import TAB_IMPORT

logger = logging.getLogger(__name__)

MAX_LOG_LINES = 400


class PersonalLibraryApp:
    """Builds the window and coordinates the tabs."""

    def __init__(self, page: ft.Page) -> None:
        self.page = page
        self.settings: Settings = load_settings()
        self.file_picker = ft.FilePicker()
        self.cancel_event = threading.Event()
        self.busy = False
        self.keys = ModifierKeys()  # Shift held? (Shift+click in the gallery)
        self.opener = BookOpener(self)  # Abrir livro (reader window, or here)
        self._action_buttons: list[ft.Control] = []
        # The open library (None if the chosen one does not exist or is not valid).
        self.library: Path | None = None
        self.books: list[LibraryBook] = []
        self._build_status_bar()
        self.library_picker = LibraryPicker(self)
        self.import_tab = ImportTab(self)
        self.gallery = GalleryTab(self)
        self.export_tab = ExportTab(self)

    # ================================================================== building

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
        """Registers the file picker and puts the three tabs in the window."""
        registry = getattr(self.page, "services", None)
        if registry is None:  # old versions of Flet use overlay
            registry = self.page.overlay
        registry.append(self.file_picker)
        if getattr(self.page, "web", False):
            # In the browser, the right button would show the browser menu, not the gallery one.
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
        # [1] is the tabs, or what replace_tabs puts there (the reader, in the web version).
        self.content = ft.Column(controls=[header, self.tabs, ft.Divider(height=1), status_bar,
                                           self.log_panel], spacing=6, expand=True)
        self.page.add(self.keys.wrap(self.content))
        self.page.on_keyboard_event = self.on_page_key
        # Window focus events only exist on desktop; on the web this never fires.
        self.page.window.on_event = self.keys.on_window_event
        self.library_picker.refresh()
        self.import_tab.refresh()
        self.export_tab.refresh()
        self.page.update()

    async def use_app_context_menus(self) -> None:
        """Web version only: turns off the browser menu (otherwise the "Abrir" of the gallery
        does not show up with the right button). In the desktop app there is nothing to do."""
        menu = getattr(self, "browser_menu", None)
        if menu is None:
            return
        try:
            await menu.disable()
        except Exception:
            logger.debug("could not turn off the browser menu", exc_info=True)

    async def on_page_key(self, event: Any) -> None:
        """Every key pressed in the window (page.on_keyboard_event)."""
        self.keys.on_page_key(event)
        await self.opener.on_key(event)

    def replace_tabs(self, control: ft.Control | None) -> None:
        """Shows `control` in place of the tabs (header and status bar stay); None brings
        the tabs back as they were."""
        self.content.controls[1] = control if control is not None else self.tabs
        self.page.update()

    async def go_to_tab(self, index: int) -> None:
        self.tabs.selected_index = index
        self.page.update()

    # ================================================================== open library

    async def open_library(self, path: str | Path | None) -> bool:
        """Switches to the library in `path` (in the three tabs). False if it is not valid."""
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
        """The tool that changes the library (None if it is not installed)."""
        return LibraryCli.find(self.settings.cli_path or None)

    # ================================================================== services

    def save(self) -> None:
        """Each tab stores its own fields in the settings; then the file is written."""
        for tab in (self.import_tab, self.export_tab, self.gallery):
            tab.store(self.settings)
        save_settings(self.settings)

    def log(self, message: str, error: bool = False) -> None:
        """Logs the message and shows the latest one in the status bar."""
        (logger.warning if error else logger.info)(message)
        color = ft.Colors.RED_700 if error else None
        self.log_view.controls.append(ft.Text(message, size=12, color=color, selectable=True))
        del self.log_view.controls[:-MAX_LOG_LINES]
        self.status_text.value, self.status_text.color = message, color
        if error:
            self.log_panel.visible = True  # an error is never hidden
        self.page.update()

    def log_errors(self, errors: list[str], limit: int = 20) -> None:
        """The errors of a job, one per line (the first ones: the rest add nothing)."""
        for error in errors[:limit]:
            self.log(f"  ✗ {error}", True)

    def register_actions(self, *buttons: ft.Control) -> None:
        """Buttons that stay disabled while a job is running."""
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
        """Runs `func` in another thread showing the progress, without freezing the window."""
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

    # ================================================================== events

    def on_toggle_log(self, _event: Any) -> None:
        self.log_panel.visible = not self.log_panel.visible
        self.page.update()

    def on_cancel(self, _event: Any) -> None:
        self.cancel_event.set()
        self.status_text.value = "Cancelando…"
        self.page.update()


async def main(page: ft.Page) -> None:
    """Entry point passed to `ft.run`."""
    page.title = APP_NAME
    page.theme_mode = ft.ThemeMode.LIGHT
    page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
    page.padding = 12
    try:
        page.window.width, page.window.height = 1200, 860
        page.window.min_width, page.window.min_height = 900, 640
        page.window.maximized = True  # more visible rows in the review list and in the gallery
    except Exception:  # window not configurable (web/mobile): no problem
        logger.debug("window not configurable", exc_info=True)
    app = PersonalLibraryApp(page)
    app.build()
    await app.use_app_context_menus()
    if app.settings.library:
        await app.open_library(app.settings.library)
