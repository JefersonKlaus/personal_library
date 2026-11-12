"""Aba Galeria: a biblioteca aberta em grade de capas, com busca, ordem e detalhes."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from ..library.database import LibraryBook
from ..library.search import SORTS, search, sort_books
from ..library.thumbnails import thumbnail
from ..paths import THUMBS_DIR
from ..settings import Settings
from .book_views import book_card, details_dialog, open_path
from .widgets import page_count, pager_controls, update_pager

if TYPE_CHECKING:  # só para o editor; evita import circular
    from .app import PersonalLibraryApp

GALLERY_PAGE_SIZE = 60
NO_LIBRARY = "Escolha a pasta da sua biblioteca para ver os livros."


class GalleryTab:
    """Mostra os livros da biblioteca aberta (app.books); não guarda a biblioteca."""

    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        self.view: list[LibraryBook] = []  # depois da busca e da ordem
        self.page_index = 0
        self._render_seq = 0  # descarta renderizações que ficaram velhas
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
        return ft.Container(padding=12, expand=True, content=ft.Column(controls=[
            library_row, self.library_status, search_row, self.body, pager,
        ], spacing=10, expand=True))

    def store(self, settings: Settings) -> None:
        settings.gallery_sort = self.sort_dropdown.value or "added"

    # ------------------------------------------------------------------ biblioteca

    def show_loading(self) -> None:
        self.loading.visible = True
        self.app.page.update()

    async def on_library_changed(self, error: str = "") -> None:
        """Chamado pelo app quando a biblioteca é aberta, recarregada ou falha."""
        self.library_field.value = self.app.settings.library
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

    # ------------------------------------------------------------------ busca, ordem, páginas

    async def apply_filters(self) -> None:
        key = self.sort_dropdown.value or "added"
        self.view = sort_books(search(self.app.books, self.search_field.value or ""), key)
        self.page_index = 0
        await self.render()

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
        """Monta a página atual da grade; as capas são preparadas em outra thread."""
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
        if seq != self._render_seq:  # o usuário já digitou/clicou outra coisa
            return
        self.loading.visible = False
        if not books or not self.view:
            self._show_empty("A biblioteca está vazia." if not books
                             else "Nenhum livro encontrado para essa busca.")
            return
        self.grid.controls = [
            book_card(book, cover, lambda _e, b=book, c=cover: self.show_details(b, c))
            for book, cover in zip(chunk, covers)]
        self.body.controls = [self.grid]
        shown = f"{len(self.view)} de {len(books)}" if len(self.view) != len(books) \
            else f"{len(books)}"
        self.count_text.value = f"{shown} livro(s)"
        update_pager(self.prev_btn, self.page_label, self.next_btn, self.page_index,
                     page_count(len(self.view), GALLERY_PAGE_SIZE))
        self.app.page.update()

    # ------------------------------------------------------------------ detalhes

    def show_details(self, book: LibraryBook, cover: bytes | None) -> None:
        page = self.app.page
        page.show_dialog(details_dialog(book, cover, self.app.library, on_open=self.open,
                                        on_close=lambda _e: page.pop_dialog()))

    def open(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.app.log("Arquivo não encontrado na biblioteca.", error=True)
            return
        try:
            open_path(path)
        except Exception as exc:
            self.app.log(f"Não foi possível abrir {path}: {exc}", error=True)
