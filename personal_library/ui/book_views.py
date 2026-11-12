"""Como um livro da biblioteca aparece: capa, cartão da grade e janela de detalhes."""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Awaitable, Callable

import flet as ft

from ..library.database import LibraryBook
from ..text import html_to_text

# Cores das capas geradas para livros sem capa.
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


def cover_view(book: LibraryBook, data: bytes | None, big: bool = False) -> ft.Control:
    """A capa; sem capa, um retângulo colorido com título e autor."""
    size: dict[str, Any] = {"width": 220, "height": 330} if big else {"expand": True}
    if data:
        # Imagem de fundo: preenche o quadro todo, então as capas da grade ficam do
        # mesmo tamanho mesmo com proporções diferentes.
        return ft.Container(image=ft.DecorationImage(src=data, fit=ft.BoxFit.COVER),
                            border_radius=6, border=ft.Border.all(1, ft.Colors.GREY_300), **size)
    return ft.Container(
        bgcolor=placeholder_color(book.title), border_radius=6, padding=10, **size,
        alignment=ft.Alignment.CENTER,
        content=ft.Column(controls=[
            ft.Icon(ft.Icons.MENU_BOOK, color=ft.Colors.WHITE, size=28),
            ft.Text(book.title, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD, size=13,
                    text_align=ft.TextAlign.CENTER, max_lines=4,
                    overflow=ft.TextOverflow.ELLIPSIS),
            ft.Text(book.authors_text, color=ft.Colors.WHITE, size=11,
                    text_align=ft.TextAlign.CENTER, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True, spacing=6))


def _volume_badge(book: LibraryBook, cover: ft.Control) -> ft.Control:
    """Volumes costumam ter o mesmo título: o número aparece sobre a capa."""
    return ft.Stack(expand=True, fit=ft.StackFit.EXPAND, controls=[
        cover,
        ft.Container(
            content=ft.Text(f"Vol. {book.series_index:g}", size=11, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
            bgcolor=ft.Colors.INDIGO_700, border_radius=10,
            padding=ft.Padding(left=8, right=8, top=2, bottom=2), right=6, top=6),
    ])


def book_card(book: LibraryBook, cover: bytes | None,
              on_click: Callable[[Any], None]) -> ft.Control:
    """Cartão da grade: capa, título (2 linhas) e autor."""
    cover_control = cover_view(book, cover)
    tooltip = f"{book.title}\n{book.authors_text}"
    if book.series:
        cover_control = _volume_badge(book, cover_control)
        tooltip += f"\n{book.series_text}"
    return ft.Container(
        ink=True, border_radius=8, padding=6, tooltip=tooltip, on_click=on_click,
        content=ft.Column(controls=[
            cover_control,
            # Altura fixa de 2 linhas: todas as capas da grade ficam do mesmo tamanho.
            ft.Container(height=34, content=ft.Text(
                book.title, size=12, weight=ft.FontWeight.BOLD, max_lines=2,
                overflow=ft.TextOverflow.ELLIPSIS)),
            ft.Text(book.authors_text, size=11, color=ft.Colors.GREY_700, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS),
        ], spacing=3, expand=True))


def details_rows(book: LibraryBook) -> list[tuple[str, str]]:
    """Os campos do livro que estão preenchidos, na ordem de exibição."""
    identifiers = ", ".join(f"{k}:{v}" for k, v in sorted(book.identifiers.items()))
    rows = [
        ("Autor(es)", book.authors_text),
        ("Série", book.series_text),
        ("Etiquetas", ", ".join(book.tags)),
        ("Editora", book.publisher),
        ("Publicado", str(book.year) if book.year else ""),
        ("Idiomas", ", ".join(book.languages)),
        ("Formatos", ", ".join(sorted(book.formats))),
        ("Identificadores", identifiers),
        ("Adicionado", book.added.strftime("%d/%m/%Y") if book.added else ""),
    ]
    return [(label, value) for label, value in rows if value]


class BookDetailsDialog:
    """Janela de detalhes: capa grande, todos os dados, 'Abrir livro' e o botão pequeno
    ao lado do título para renomear o livro."""

    def __init__(self, book: LibraryBook, cover: bytes | None, library: Path,
                 on_open: Callable[[Path | None], None], on_close: Callable[[Any], None],
                 on_rename: Callable[[LibraryBook, str], Awaitable[bool]],
                 update: Callable[[], None]) -> None:
        self.book = book
        self.on_rename = on_rename
        self.update = update
        # expand_loose: o título ocupa só a largura que precisa (o lápis fica colado nele),
        # mas títulos longos ainda quebram linha em vez de estourar a janela.
        self.title_text = ft.Text(book.title, size=20, weight=ft.FontWeight.BOLD, expand=True,
                                  expand_loose=True)
        self.title_field = ft.TextField(value=book.title, dense=True, expand=True,
                                        autofocus=True, on_submit=self.save)
        self.edit_button = ft.IconButton(icon=ft.Icons.EDIT, icon_size=16,
                                         tooltip="Renomear livro",
                                         visual_density=ft.VisualDensity.COMPACT,
                                         on_click=self.start_edit)
        self.title_row = ft.Row(controls=[self.title_text, self.edit_button],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER)
        main_file = book.main_file(library)
        self.dialog = ft.AlertDialog(
            title=self.title_row,
            content=ft.Container(width=660, height=340, content=ft.Row(controls=[
                cover_view(book, cover, big=True),
                ft.Column(controls=self._info(), scroll=ft.ScrollMode.AUTO, expand=True,
                          spacing=6),
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=18)),
            actions=[
                ft.FilledButton("Abrir livro", icon=ft.Icons.OPEN_IN_NEW,
                                on_click=lambda _e: on_open(main_file),
                                disabled=main_file is None),
                ft.TextButton("Fechar", on_click=on_close),
            ])

    def _info(self) -> list[ft.Control]:
        info: list[ft.Control] = [
            ft.Row(controls=[ft.Text(label, size=12, weight=ft.FontWeight.BOLD, width=110),
                             ft.Text(value, size=12, selectable=True, expand=True)],
                   vertical_alignment=ft.CrossAxisAlignment.START)
            for label, value in details_rows(self.book)]
        comments = html_to_text(self.book.comments)
        if comments:
            info += [ft.Divider(), ft.Text(comments, size=12, selectable=True)]
        return info

    def start_edit(self, _event: Any) -> None:
        self.title_field.value = self.title_text.value
        self.title_row.controls = [
            self.title_field,
            ft.IconButton(icon=ft.Icons.CHECK, icon_size=18, tooltip="Salvar",
                          visual_density=ft.VisualDensity.COMPACT, on_click=self.save),
            ft.IconButton(icon=ft.Icons.CLOSE, icon_size=18, tooltip="Cancelar",
                          visual_density=ft.VisualDensity.COMPACT, on_click=self.cancel_edit),
        ]
        self.update()

    def cancel_edit(self, _event: Any = None) -> None:
        self.title_row.controls = [self.title_text, self.edit_button]
        self.update()

    async def save(self, _event: Any) -> None:
        new_title = self.title_field.value or ""
        if await self.on_rename(self.book, new_title):
            self.title_text.value = " ".join(new_title.split())
            self.cancel_edit()
