"""Aba Galeria: mostra uma biblioteca do Calibre em grade de capas, como o Calibre."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from . import calibre
from . import library as lib
from .settings import CONFIG_DIR

if TYPE_CHECKING:  # evita import circular; só para o editor
    from .ui import PersonalLibraryApp

logger = logging.getLogger(__name__)

GALLERY_PAGE_SIZE = 60
THUMB_CACHE = CONFIG_DIR / "thumbs"
# Cores das capas geradas para livros sem capa (como o Calibre faz).
PLACEHOLDER_COLORS = ["#37474F", "#4E342E", "#1B5E20", "#0D47A1", "#4A148C", "#B71C1C", "#006064"]


def open_path(path: Path) -> None:
    """Abre um arquivo ou pasta com o programa padrão do sistema."""
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


def placeholder_color(title: str) -> str:
    digest = hashlib.md5(title.encode("utf-8")).digest()
    return PLACEHOLDER_COLORS[digest[0] % len(PLACEHOLDER_COLORS)]


class GalleryView:
    """Controles e eventos da aba Galeria."""

    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        self.page = app.page
        self.library: Path | None = None
        self.books: list[lib.LibraryBook] = []  # tudo o que foi lido
        self.view: list[lib.LibraryBook] = []  # depois da busca e da ordem
        self.page_index = 0
        self._render_seq = 0  # descarta renderizações que ficaram velhas
        self.thumb_cache: Path | None = THUMB_CACHE
        settings = app.settings

        self.library_field = ft.TextField(
            label="Biblioteca do Calibre (pasta com metadata.db)", value=settings.library,
            dense=True, expand=True, on_submit=self.on_library_submit)
        self.library_status = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.search_field = ft.TextField(
            hint_text="Buscar por título, autor, etiqueta, série ou editora",
            prefix_icon=ft.Icons.SEARCH, dense=True, expand=True, on_change=self.on_search)
        self.sort_dropdown = ft.Dropdown(
            label="Ordenar por", dense=True, width=220,
            value=settings.gallery_sort if settings.gallery_sort in lib.SORTS else "added",
            options=[ft.DropdownOption(key=key, text=text) for key, text in lib.SORTS.items()],
            on_select=self.on_sort)
        self.count_text = ft.Text(size=12, color=ft.Colors.GREY_700)
        self.grid = ft.GridView(
            controls=[], expand=True, max_extent=170, child_aspect_ratio=0.56,
            spacing=14, run_spacing=14, padding=4)
        self.empty_text = ft.Text(
            "Escolha a pasta da sua biblioteca do Calibre para ver os livros.",
            size=14, color=ft.Colors.GREY_700, text_align=ft.TextAlign.CENTER)
        self.empty_state = ft.Container(
            content=ft.Column(controls=[
                ft.Icon(ft.Icons.COLLECTIONS_BOOKMARK, size=56, color=ft.Colors.GREY_400),
                self.empty_text,
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            alignment=ft.Alignment.CENTER, expand=True)
        self.loading = ft.ProgressRing(width=22, height=22, visible=False)
        self.prev_btn = ft.OutlinedButton("Anterior", on_click=self.on_prev, disabled=True)
        self.next_btn = ft.OutlinedButton("Próxima", on_click=self.on_next, disabled=True)
        self.page_label = ft.Text(size=12)

    # ------------------------------------------------------------------ montagem

    def build(self) -> ft.Control:
        library_row = ft.Row(controls=[
            self.library_field,
            ft.OutlinedButton("Escolher…", icon=ft.Icons.FOLDER_OPEN, on_click=self.on_pick_library),
            ft.OutlinedButton("Criar nova…", icon=ft.Icons.CREATE_NEW_FOLDER,
                              on_click=self.app.on_create_library),
            ft.IconButton(icon=ft.Icons.REFRESH, tooltip="Recarregar", on_click=self.on_reload),
        ])
        search_row = ft.Row(controls=[
            self.search_field, self.sort_dropdown, self.loading,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        pager = ft.Row(controls=[
            self.count_text, ft.Container(expand=True),
            self.prev_btn, self.page_label, self.next_btn,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.body = ft.Column(controls=[self.empty_state], expand=True)
        return ft.Container(padding=12, expand=True, content=ft.Column(controls=[
            library_row, self.library_status, search_row, self.body, pager,
        ], spacing=10, expand=True))

    # ------------------------------------------------------------------ biblioteca

    async def on_pick_library(self, _event: Any) -> None:
        folder = await self.app.pick_directory("Escolha a biblioteca do Calibre")
        if folder:
            # Aceita também a pasta de cima ("Documentos" em vez de "Documentos/Calibre Library").
            found = calibre.find_library_in(folder)
            await self.load(str(found) if found else folder)

    async def on_library_submit(self, _event: Any) -> None:
        await self.load(self.library_field.value)

    async def on_reload(self, _event: Any) -> None:
        await self.load(self.library_field.value)

    async def load(self, folder: str | None) -> None:
        """Lê a biblioteca (em outra thread) e mostra a primeira página."""
        folder = (folder or "").strip().strip('"')
        self.library_field.value = folder  # save() lê o campo
        self.app.save()
        self.app.refresh_library_info()
        if not folder:
            self.library, self.books = None, []
            self.app.on_library_loaded([], changed=True)
            self._show_empty("Escolha a pasta da sua biblioteca do Calibre para ver os livros.")
            return
        self.loading.visible = True
        self.page.update()
        try:
            books = await asyncio.to_thread(lib.load_library, Path(folder))
        except lib.LibraryError as exc:
            self.library, self.books = None, []
            self.loading.visible = False
            self.library_status.value = str(exc)
            self.library_status.color = ft.Colors.RED_700
            self.app.on_library_loaded([], changed=True)
            self._show_empty("Essa pasta não é uma biblioteca do Calibre.\n"
                             "Escolha a pasta que contém o arquivo metadata.db.")
            return
        changed = self.library is None or self.library != Path(folder)
        self.library, self.books = Path(folder), books
        self.app.on_library_loaded(books, changed)
        self.library_status.value = f"{len(books)} livro(s) em {folder}"
        self.library_status.color = ft.Colors.GREEN_800
        self.app.log(f"Galeria: {len(books)} livro(s) lidos de {folder}.")
        await self.apply_filters()

    # ------------------------------------------------------------------ busca, ordem, páginas

    async def apply_filters(self) -> None:
        key = self.sort_dropdown.value or "added"
        self.view = lib.sort_books(lib.search(self.books, self.search_field.value or ""), key)
        self.page_index = 0
        await self.render()

    async def on_search(self, _event: Any) -> None:
        await self.apply_filters()

    async def on_sort(self, _event: Any) -> None:
        self.app.settings.gallery_sort = self.sort_dropdown.value or "added"
        self.app.save()
        await self.apply_filters()

    def _page_count(self) -> int:
        return max(1, -(-len(self.view) // GALLERY_PAGE_SIZE))

    async def on_prev(self, _event: Any) -> None:
        self.page_index = max(0, self.page_index - 1)
        await self.render()

    async def on_next(self, _event: Any) -> None:
        self.page_index = min(self._page_count() - 1, self.page_index + 1)
        await self.render()

    def _show_empty(self, message: str) -> None:
        self.empty_text.value = message
        self.body.controls = [self.empty_state]
        self.grid.controls = []
        self.count_text.value = ""
        self.page_label.value = ""
        self.prev_btn.disabled = self.next_btn.disabled = True
        self.loading.visible = False
        self.page.update()

    async def render(self) -> None:
        """Monta a página atual da grade; as capas são preparadas em outra thread."""
        if self.library is None:
            return
        self._render_seq += 1
        seq = self._render_seq
        start = self.page_index * GALLERY_PAGE_SIZE
        chunk = self.view[start:start + GALLERY_PAGE_SIZE]
        self.loading.visible = True
        self.page.update()
        library, cache = self.library, self.thumb_cache
        covers = await asyncio.to_thread(
            lambda: [lib.thumbnail(book, library, cache) for book in chunk])
        if seq != self._render_seq:  # o usuário já digitou/clicou outra coisa
            return
        self.loading.visible = False
        if not self.books:
            self._show_empty("A biblioteca está vazia.")
            return
        if not self.view:
            self._show_empty("Nenhum livro encontrado para essa busca.")
            return
        self.grid.controls = [self._card(book, cover) for book, cover in zip(chunk, covers)]
        self.body.controls = [self.grid]
        pages = self._page_count()
        shown = f"{len(self.view)} de {len(self.books)}" if len(self.view) != len(self.books) \
            else f"{len(self.books)}"
        self.count_text.value = f"{shown} livro(s)"
        self.page_label.value = f"Página {self.page_index + 1} de {pages}"
        self.prev_btn.disabled = self.page_index == 0
        self.next_btn.disabled = self.page_index >= pages - 1
        for control in (self.prev_btn, self.page_label, self.next_btn):
            control.visible = pages > 1
        self.page.update()

    # ------------------------------------------------------------------ cartões e detalhes

    def _cover(self, book: lib.LibraryBook, data: bytes | None, big: bool = False) -> ft.Control:
        size = {"width": 220, "height": 330} if big else {"expand": True}
        if data:
            # Imagem de fundo: preenche o quadro todo, então todas as capas ficam do
            # mesmo tamanho (como na grade do Calibre), mesmo com proporções diferentes.
            return ft.Container(
                image=ft.DecorationImage(src=data, fit=ft.BoxFit.COVER), border_radius=6,
                border=ft.Border.all(1, ft.Colors.GREY_300), **size)
        # Sem capa: um retângulo colorido com o título, como o Calibre gera.
        return ft.Container(
            bgcolor=placeholder_color(book.title), border_radius=6, padding=10, **size,
            alignment=ft.Alignment.CENTER,
            content=ft.Column(controls=[
                ft.Icon(ft.Icons.MENU_BOOK, color=ft.Colors.WHITE, size=28),
                ft.Text(book.title, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD,
                        size=13, text_align=ft.TextAlign.CENTER, max_lines=4,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(book.authors_text, color=ft.Colors.WHITE, size=11,
                        text_align=ft.TextAlign.CENTER, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True, spacing=6))

    def _card(self, book: lib.LibraryBook, cover: bytes | None) -> ft.Control:
        cover_control = self._cover(book, cover)
        if book.series:
            # Volumes costumam ter o mesmo título: o número aparece na capa.
            cover_control = ft.Stack(expand=True, fit=ft.StackFit.EXPAND, controls=[
                cover_control,
                ft.Container(
                    content=ft.Text(f"Vol. {book.series_index:g}", size=11,
                                    color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
                    bgcolor=ft.Colors.INDIGO_700, border_radius=10, padding=ft.Padding(
                        left=8, right=8, top=2, bottom=2), right=6, top=6),
            ])
        tooltip = f"{book.title}\n{book.authors_text}"
        if book.series:
            tooltip += f"\n{book.series_text}"
        return ft.Container(
            ink=True, border_radius=8, padding=6, tooltip=tooltip,
            on_click=lambda _e, item=book, data=cover: self.show_details(item, data),
            content=ft.Column(controls=[
                cover_control,
                # Altura fixa de 2 linhas: todas as capas da grade ficam do mesmo tamanho.
                ft.Container(height=34, content=ft.Text(
                    book.title, size=12, weight=ft.FontWeight.BOLD, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Text(book.authors_text, size=11, color=ft.Colors.GREY_700, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=3, expand=True))

    def details_rows(self, book: lib.LibraryBook) -> list[tuple[str, str]]:
        """Os campos que o Calibre mostra no painel de detalhes (só os preenchidos)."""
        rows = [
            ("Autor(es)", book.authors_text),
            ("Série", book.series_text),
            ("Etiquetas", ", ".join(book.tags)),
            ("Editora", book.publisher),
            ("Publicado", str(book.year) if book.year else ""),
            ("Idiomas", ", ".join(book.languages)),
            ("Formatos", ", ".join(sorted(book.formats))),
            ("Identificadores", ", ".join(f"{k}:{v}" for k, v in sorted(book.identifiers.items()))),
            ("Adicionado", book.added.strftime("%d/%m/%Y") if book.added else ""),
        ]
        return [(label, value) for label, value in rows if value]

    def show_details(self, book: lib.LibraryBook, cover: bytes | None) -> None:
        assert self.library is not None
        library = self.library
        info: list[ft.Control] = []
        for label, value in self.details_rows(book):
            info.append(ft.Row(controls=[
                ft.Text(label, size=12, weight=ft.FontWeight.BOLD, width=110),
                ft.Text(value, size=12, selectable=True, expand=True),
            ], vertical_alignment=ft.CrossAxisAlignment.START))
        comments = lib.plain_text(book.comments)
        if comments:
            info += [ft.Divider(), ft.Text(comments, size=12, selectable=True)]
        main_file = book.main_file(library)

        def close(_e: Any = None) -> None:
            self.page.pop_dialog()

        def open_book(_e: Any) -> None:
            self._open(main_file)

        def open_folder(_e: Any) -> None:
            self._open(book.folder(library))

        dialog = ft.AlertDialog(
            title=ft.Text(book.title, weight=ft.FontWeight.BOLD),
            content=ft.Container(width=660, height=340, content=ft.Row(controls=[
                self._cover(book, cover, big=True),
                ft.Column(controls=info, scroll=ft.ScrollMode.AUTO, expand=True, spacing=6),
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=18)),
            actions=[
                ft.TextButton("Abrir pasta", icon=ft.Icons.FOLDER_OPEN, on_click=open_folder),
                ft.FilledButton("Abrir livro", icon=ft.Icons.OPEN_IN_NEW, on_click=open_book,
                                disabled=main_file is None),
                ft.TextButton("Fechar", on_click=close),
            ])
        self.page.show_dialog(dialog)

    def _open(self, path: Path | None) -> None:
        if path is None or not path.exists():
            self.app.log("Arquivo não encontrado na biblioteca.", error=True)
            return
        try:
            open_path(path)
        except Exception as exc:
            self.app.log(f"Não foi possível abrir {path}: {exc}", error=True)
