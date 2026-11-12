"""Aba Galeria: a biblioteca aberta em grade de capas, com séries, busca, ordem e detalhes."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from ..library.cli import LibraryCli
from ..library.database import LibraryBook
from ..library.manager import PRODUCT
from ..library.search import NO_SERIES, SORTS, in_series, search, sort_books
from ..library.thumbnails import thumbnail
from ..paths import THUMBS_DIR
from ..renamer import RenameError, rename_book, rename_series
from ..settings import Settings
from .book_views import BookCard, BookDetailsDialog, open_path
from .series_sidebar import SeriesSidebar
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
        self.cards: list[BookCard] = []  # os cartões da página atual
        self.selected_id: int | None = None  # o livro selecionado (um clique)
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

    # ------------------------------------------------------------------ biblioteca

    def show_loading(self) -> None:
        self.loading.visible = True
        self.app.page.update()

    async def on_library_changed(self, error: str = "") -> None:
        """Chamado pelo app quando a biblioteca é aberta, recarregada ou falha."""
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

    # ------------------------------------------------------------------ busca, ordem, páginas

    async def apply_filters(self) -> None:
        """Série escolhida na barra lateral + busca + ordem."""
        books = in_series(self.app.books, self.sidebar.selected)
        self.view = sort_books(search(books, self.search_field.value or ""),
                               self.sort_dropdown.value or "added")
        self.page_index = 0
        await self.render()

    async def select_series(self, series: str | None) -> None:
        """Dentro de uma série, os volumes em ordem é o que faz sentido (dá para mudar)."""
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
                             else "Nenhum livro encontrado para essa busca nesta série."
                             if self.sidebar.selected is not None
                             else "Nenhum livro encontrado para essa busca.")
            return
        self.cards = [self._card(book, cover) for book, cover in zip(chunk, covers)]
        self.grid.controls = [card.control for card in self.cards]
        self.body.controls = [self.grid]
        shown = f"{len(self.view)} de {len(books)}" if len(self.view) != len(books) \
            else f"{len(books)}"
        self.count_text.value = f"{shown} livro(s)"
        update_pager(self.prev_btn, self.page_label, self.next_btn, self.page_index,
                     page_count(len(self.view), GALLERY_PAGE_SIZE))
        self.app.page.update()

    # ------------------------------------------------------------------ seleção e detalhes

    def _card(self, book: LibraryBook, cover: bytes | None) -> BookCard:
        def on_open(_event: Any) -> None:
            self.select(book.id)
            self.show_details(book, cover)

        return BookCard(book, cover, book.id == self.selected_id,
                        on_select=lambda _e: self.select(book.id), on_open=on_open)

    def select(self, book_id: int) -> None:
        """Um clique: destaca o livro (só os cartões que mudam são redesenhados)."""
        self.selected_id = book_id
        for card in self.cards:
            if card.selected != (card.book.id == book_id):
                card.set_selected(not card.selected)
        self.app.page.update()

    def show_details(self, book: LibraryBook, cover: bytes | None) -> None:
        page = self.app.page
        details = BookDetailsDialog(book, cover, self.app.library, on_open=self.open,
                                    on_close=lambda _e: page.pop_dialog(),
                                    on_rename=self.rename_book, update=page.update)
        page.show_dialog(details.dialog)

    def open(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.app.log("Arquivo não encontrado na biblioteca.", error=True)
            return
        try:
            open_path(path)
        except Exception as exc:
            self.app.log(f"Não foi possível abrir {path}: {exc}", error=True)

    # ------------------------------------------------------------------ renomear

    def _ready_to_edit(self) -> LibraryCli | None:
        """A ferramenta que altera a biblioteca, ou None (com a mensagem já mostrada)."""
        if self.app.busy or self.app.library is None:
            return None
        cli = self.app.cli()
        if cli is None:
            self.app.log(f"{PRODUCT} não encontrado: instale-o para renomear.", True)
        return cli

    async def rename_book(self, book: LibraryBook, new_title: str) -> bool:
        """Renomeia um livro (botão ao lado do título). True se deu certo."""
        cli, library = self._ready_to_edit(), self.app.library
        if cli is None:
            return False
        self.app.set_busy(True)
        try:
            ok, error = await asyncio.to_thread(rename_book, cli, library, book, new_title)
        except RenameError as exc:
            ok, error = False, str(exc)
        finally:
            self.app.set_busy(False)
        if not ok:
            self.app.log(f"Não foi possível renomear o livro: {error}", True)
            return False
        await self.app.open_library(library)
        self.app.log(f"Livro renomeado: '{book.title}' agora é '{' '.join(new_title.split())}'.")
        return True

    async def rename_series(self, old: str, new: str, rename_titles: bool) -> None:
        """Renomeia a série em todos os livros dela (botão na barra lateral)."""
        cli, library = self._ready_to_edit(), self.app.library
        if cli is None:
            return
        try:
            report = await self.app.run_job(rename_series, cli, library, self.app.books, old,
                                            new, rename_titles, label="Renomeando a série")
        except RenameError as exc:
            self.app.log(str(exc), True)
            return
        for error in report.errors[:20]:
            self.app.log(f"  ✗ {error}", True)
        new = " ".join(new.split())
        if self.sidebar.selected == old and report.done:
            self.sidebar.selected = new  # continua mostrando a mesma série, com o nome novo
        await self.app.open_library(library)
        self.app.log(f"Série '{old}' renomeada para '{new}': {report.done} de {report.total} "
                     f"livro(s){' (cancelado)' if report.cancelled else ''}.",
                     error=bool(report.failed))
