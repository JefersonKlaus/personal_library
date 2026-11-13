"""Galeria tab: the open library as a grid of covers, with series, search, order and details."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from ..core.paths import THUMBS_DIR
from ..core.settings import Settings
from ..library.database import LibraryBook
from ..library.metadata_editor import apply_changes
from ..library.renamer import rename_book, rename_series
from ..library.search import NO_SERIES, SORTS, in_series, search, sort_books
from ..library.thumbnails import thumbnail
from .book_views import BookCard, BookDetailsDialog
from .library_edits import LibraryEdits
from .metadata_dialog import MetadataDialog
from .selection import Selection
from .series_sidebar import SeriesSidebar
from .widgets import page_count, pager_controls, update_pager

if TYPE_CHECKING:  # for the editor only; avoids a circular import
    from .app import PersonalLibraryApp

GALLERY_PAGE_SIZE = 60
NO_LIBRARY = "Escolha a pasta da sua biblioteca para ver os livros."


class GalleryTab:
    """Shows the books of the open library (app.books) as a grid of covers, with the
    series sidebar, search, order and pages, and wires each card to what it does:
    selecting (Selection), opening (app.opener) and changing the library (LibraryEdits).
    Does not hold the library."""

    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        self.view: list[LibraryBook] = []  # after the search and the order
        self.page_index = 0
        self._render_seq = 0  # drops renders that went stale
        self.cards: list[BookCard] = []  # the cards of the current page
        self.selection = Selection()
        self.edits = LibraryEdits(app)
        self.thumb_cache: Path | None = THUMBS_DIR
        self.library_field = ft.TextField(
            label="Biblioteca (pasta da biblioteca)", value=app.settings.library, dense=True,
            expand=True, on_submit=self.on_reload)
        self.library_status = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.search_field = ft.TextField(
            hint_text="Buscar por título, autor, etiqueta, série ou editora",
            prefix_icon=ft.Icons.SEARCH, dense=True, expand=True, on_change=self.on_search)
        sort = app.settings.gallery_sort
        self.sort_dropdown = ft.Dropdown(
            label="Ordenar por", dense=True, width=220, value=sort if sort in SORTS else "added",
            options=[ft.DropdownOption(key=key, text=text) for key, text in SORTS.items()],
            on_select=self.on_sort)
        self.count_text = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.grid = ft.GridView(controls=[], expand=True, max_extent=170,
                                child_aspect_ratio=0.56, spacing=14, run_spacing=14, padding=4)
        self.empty_text = ft.Text(NO_LIBRARY, size=14, color=ft.Colors.GREY_700,
                                  text_align=ft.TextAlign.CENTER)
        self.empty_state = ft.Container(
            content=ft.Column(controls=[
                ft.Icon(ft.Icons.COLLECTIONS_BOOKMARK, size=56, color=ft.Colors.GREY_400),
                self.empty_text,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            alignment=ft.Alignment.CENTER, expand=True)
        self.body = ft.Column(controls=[self.empty_state], expand=True)
        self.loading = ft.ProgressRing(width=22, height=22, visible=False)
        self.prev_btn, self.page_label, self.next_btn = pager_controls(self.on_prev, self.on_next)
        self.sidebar = SeriesSidebar(app.page, on_select=self.select_series,
                                     on_rename=self.rename_series)

    def build(self) -> ft.Control:
        picker = self.app.library_picker
        library_row = ft.Row(controls=[
            self.library_field,
            ft.OutlinedButton("Escolher…", icon=ft.Icons.FOLDER_OPEN, on_click=picker.on_choose),
            ft.OutlinedButton("Criar nova…", icon=ft.Icons.CREATE_NEW_FOLDER,
                              on_click=picker.on_create),
            ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Recarregar", on_click=self.on_reload),
        ])
        search_row = ft.Row(controls=[self.search_field, self.sort_dropdown, self.loading],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        pager = ft.Row(controls=[self.count_text, ft.Container(expand=True), self.prev_btn,
                                 self.page_label, self.next_btn],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER)
        books_area = ft.Column(controls=[search_row, self.body, pager], spacing=10, expand=True)
        return ft.Container(padding=12, expand=True, content=ft.Column(controls=[
            library_row, self.library_status,
            ft.Row(controls=[self.sidebar.container, books_area], spacing=12, expand=True,
                   vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        ], spacing=10, expand=True))

    def store(self, settings: Settings) -> None:
        settings.gallery_sort = self.sort_dropdown.value or "added"

    # ------------------------------------------------------------------ library

    def show_loading(self) -> None:
        self.loading.visible = True
        self.app.page.update()

    async def on_library_changed(self, error: str = "") -> None:
        """Called by the app when the library is opened, reloaded or fails."""
        self.library_field.value = self.app.settings.library
        self.sidebar.refresh(self.app.books)
        if self.app.library is None:
            self.library_status.value = error
            self.library_status.color = ft.Colors.RED_700
            self._show_empty(NO_LIBRARY if not error else
                             "Essa pasta não é uma biblioteca. Escolha a pasta da biblioteca "
                             "ou crie uma nova.")
            return
        self.library_status.value = f"{len(self.app.books)} livro(s) em {self.app.library}"
        self.library_status.color = ft.Colors.GREEN_800
        await self.apply_filters()

    async def on_reload(self, _event: Any) -> None:
        await self.app.open_library(self.library_field.value)

    # ------------------------------------------------------------------ search, order, pages

    async def apply_filters(self) -> None:
        """Series chosen in the sidebar + search + order."""
        books = in_series(self.app.books, self.sidebar.selected)
        self.view = sort_books(search(books, self.search_field.value or ""),
                               self.sort_dropdown.value or "added")
        self.page_index = 0
        await self.render()

    async def select_series(self, series: str | None) -> None:
        """Inside a series, volumes in order is what makes sense (it can be changed)."""
        if series not in (None, NO_SERIES):
            self.sort_dropdown.value = "series"
        await self.apply_filters()

    async def on_search(self, _event: Any) -> None:
        await self.apply_filters()

    async def on_sort(self, _event: Any) -> None:
        self.app.save()
        await self.apply_filters()

    async def on_prev(self, _event: Any) -> None:
        self.page_index = max(0, self.page_index - 1)
        await self.render()

    async def on_next(self, _event: Any) -> None:
        self.page_index = min(page_count(len(self.view), GALLERY_PAGE_SIZE) - 1,
                              self.page_index + 1)
        await self.render()

    def _show_empty(self, message: str) -> None:
        self.empty_text.value = message
        self.body.controls, self.grid.controls = [self.empty_state], []
        self.count_text.value = ""
        update_pager(self.prev_btn, self.page_label, self.next_btn, 0, 1)
        self.loading.visible = False
        self.app.page.update()

    async def render(self) -> None:
        """Builds the current page of the grid; the covers are prepared in another thread."""
        library, books = self.app.library, self.app.books
        if library is None:
            return
        self._render_seq += 1
        seq = self._render_seq
        start = self.page_index * GALLERY_PAGE_SIZE
        chunk = self.view[start:start + GALLERY_PAGE_SIZE]
        self.loading.visible = True
        self.app.page.update()
        cache = self.thumb_cache
        covers = await asyncio.to_thread(lambda: [thumbnail(b, library, cache) for b in chunk])
        if seq != self._render_seq:  # the user already typed/clicked something else
            return
        self.loading.visible = False
        if not books or not self.view:
            self._show_empty("A biblioteca está vazia." if not books
                             else "Nenhum livro encontrado para essa busca nesta série."
                             if self.sidebar.selected is not None
                             else "Nenhum livro encontrado para essa busca.")
            return
        self.cards = [self._card(book, cover) for book, cover in zip(chunk, covers)]
        self.grid.controls = [card.control for card in self.cards]
        self.body.controls = [self.grid]
        self._update_count()
        update_pager(self.prev_btn, self.page_label, self.next_btn, self.page_index,
                     page_count(len(self.view), GALLERY_PAGE_SIZE))
        self.app.page.update()

    def _update_count(self) -> None:
        books = self.app.books
        shown = f"{len(self.view)} de {len(books)}" if len(self.view) != len(books) \
            else f"{len(books)}"
        text = f"{shown} livro(s)"
        # A Shift+click range can reach books on other pages: the count shows all of them.
        selected = self.selection.count_in(self._order())
        if selected > 1:
            text += f" · {selected} selecionados"
        self.count_text.value = text

    # ------------------------------------------------------------------ selection and details

    def _order(self) -> list[int]:
        """The ids of the books shown, in order (what a Shift+click range follows)."""
        return [book.id for book in self.view]

    def _card(self, book: LibraryBook, cover: bytes | None) -> BookCard:
        def on_open(_event: Any) -> None:
            self._keep_or_select(book.id)
            self.show_details(book, cover)

        return BookCard(book, cover, book.id in self.selection,
                        on_select=lambda _e: self.click(book.id), on_open=on_open,
                        on_context=lambda _e: self._keep_or_select(book.id),
                        on_edit=lambda _e: self.edit_metadata(book, cover))

    def click(self, book_id: int) -> None:
        """Left click (with Ctrl/Shift held or not): see Selection.click."""
        # Takes the keyboard focus off the search field, so Shift/Ctrl are heard.
        self.app.page.run_task(self.app.keys.focus)
        keys = self.app.keys
        self.selection.click(book_id, self._order(), shift=keys.shift, ctrl=keys.ctrl)
        self._show_selection()

    def select(self, book_id: int) -> None:
        self.selection.only(book_id)
        self._show_selection()

    def _keep_or_select(self, book_id: int) -> None:
        """Right button or opening: a selected book keeps the selection (file manager)."""
        if book_id not in self.selection:
            self.select(book_id)

    def _show_selection(self) -> None:
        """Highlights the selected books (only the cards that change are redrawn)."""
        for card in self.cards:
            if card.selected != (card.book.id in self.selection):
                card.set_selected(not card.selected)
        self._update_count()
        self.app.page.update()

    def show_details(self, book: LibraryBook, cover: bytes | None) -> None:
        page = self.app.page
        details = BookDetailsDialog(book, cover, self.app.library, on_open=self.app.opener.open,
                                    on_close=lambda _e: page.pop_dialog(),
                                    on_rename=self.rename_book, update=page.update)
        page.show_dialog(details.dialog)

    # ------------------------------------------------------------------ changing the library

    def edit_metadata(self, book: LibraryBook, cover: bytes | None) -> None:
        """Right button > Editar metadados: the selected books (when the clicked one is
        among them) or only the clicked one. Only books on screen count: a selected
        book hidden by the search or series filter is not changed."""
        self._keep_or_select(book.id)
        books = [item for item in self.view if item.id in self.selection]
        page = self.app.page
        dialog = MetadataDialog(books, cover if len(books) == 1 else None,
                                on_save=self.save_metadata, close=page.pop_dialog,
                                update=page.update)
        page.show_dialog(dialog.dialog)

    async def save_metadata(self, books: list[LibraryBook], values: dict[str, str]) -> None:
        report = await self.edits.run(apply_changes, books, values, label="Gravando metadados")
        if report is None:
            return
        if report.done:
            await self.app.open_library(self.app.library)  # gallery, sidebar, export see it
        self.app.log(report.summary(), error=bool(report.failed))

    async def rename_book(self, book: LibraryBook, new_title: str) -> bool:
        """Renames a book (button next to the title). True if it worked."""
        result = await self.edits.run_one(rename_book, book, new_title)
        if result is None:
            return False
        ok, error = result
        if not ok:
            self.app.log(f"Não foi possível renomear o livro: {error}", True)
            return False
        await self.app.open_library(self.app.library)
        self.app.log(f"Livro renomeado: '{book.title}' agora é '{' '.join(new_title.split())}'.")
        return True

    async def rename_series(self, old: str, new: str, rename_titles: bool) -> None:
        """Renames the series in every book of it (button in the sidebar)."""
        report = await self.edits.run(rename_series, self.app.books, old, new, rename_titles,
                                      label="Renomeando a série")
        if report is None:
            return
        new = " ".join(new.split())
        if self.sidebar.selected == old and report.done:
            self.sidebar.selected = new  # keeps showing the same series, under the new name
        await self.app.open_library(self.app.library)
        self.app.log(f"Série '{old}' renomeada para '{new}': {report.done} de {report.total} "
                     f"livro(s){' (cancelado)' if report.cancelled else ''}.",
                     error=bool(report.failed))
