"""How a book of the library looks: cover, grid card and details window."""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any, Awaitable, Callable

import flet as ft

from ..core.text import html_to_text
from ..library.database import LibraryBook

# Colours of the covers generated for books without one.
PLACEHOLDER_COLORS = ["#37474F", "#4E342E", "#1B5E20", "#0D47A1", "#4A148C", "#B71C1C", "#006064"]

# Two clicks on the same card within this interval count as a double click
# (the same default as Windows).
DOUBLE_CLICK_SECONDS = 0.5


def placeholder_color(title: str) -> str:
    digest = hashlib.md5(title.encode("utf-8")).digest()
    return PLACEHOLDER_COLORS[digest[0] % len(PLACEHOLDER_COLORS)]


def cover_view(book: LibraryBook, data: bytes | None, big: bool = False) -> ft.Control:
    """The cover; without one, a coloured rectangle with title and author."""
    size: dict[str, Any] = {"width": 220, "height": 330} if big else {"expand": True}
    if data:
        # Background image: fills the whole frame, so the covers of the grid are all the
        # same size even with different aspect ratios.
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
    """Volumes usually share the same title: the number appears over the cover."""
    return ft.Stack(expand=True, fit=ft.StackFit.EXPAND, controls=[
        cover,
        ft.Container(
            content=ft.Text(f"Vol. {book.series_index:g}", size=11, color=ft.Colors.WHITE,
                            weight=ft.FontWeight.BOLD),
            bgcolor=ft.Colors.INDIGO_700, border_radius=10,
            padding=ft.Padding(left=8, right=8, top=2, bottom=2), right=6, top=6),
    ])


Handler = Callable[[Any], Any]


class BookCard:
    """Grid card: cover, title (2 lines) and author.

    Like in a file manager: one click selects (Shift+click selects a range: that is up to
    `on_select`); two clicks, or right button > Abrir, open the details window; right
    button > Editar metadados calls `on_edit`. The right button calls `on_context` first,
    so it can keep a selection of several books.

    The double click is detected here, not with the on_double_tap of the GestureDetector:
    with on_double_tap present, Flutter holds every left click for ~300 ms waiting for a
    possible second click before firing on_tap, and the selection was delayed (the right
    button, without that wait, was instant). With on_tap_down the left click selects the
    moment the button is pressed, just like the right one."""

    def __init__(self, book: LibraryBook, cover: bytes | None, selected: bool,
                 on_select: Handler, on_open: Handler, on_context: Handler,
                 on_edit: Handler) -> None:
        self.book = book
        self.on_select, self.on_open = on_select, on_open
        self._last_tap: float | None = None  # time of the previous click (double click)
        cover_control = cover_view(book, cover)
        tooltip = f"{book.title}\n{book.authors_text}"
        if book.series:
            cover_control = _volume_badge(book, cover_control)
            tooltip += f"\n{book.series_text}"
        self.frame = ft.Container(
            border_radius=8, padding=6, tooltip=tooltip,
            content=ft.Column(controls=[
                cover_control,
                # Fixed height of 2 lines: every cover of the grid keeps the same size.
                ft.Container(height=34, content=ft.Text(
                    book.title, size=12, weight=ft.FontWeight.BOLD, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS)),
                ft.Text(book.authors_text, size=11, color=ft.Colors.GREY_700, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=3, expand=True))
        self.set_selected(selected)
        self.control = ft.ContextMenu(
            content=ft.GestureDetector(content=self.frame, mouse_cursor=ft.MouseCursor.CLICK,
                                       on_tap_down=self.on_tap_down,
                                       on_secondary_tap_down=on_context),
            secondary_items=[
                ft.PopupMenuItem(content="Abrir", icon=ft.Icons.OPEN_IN_NEW, on_click=on_open),
                ft.PopupMenuItem(content="Editar metadados", icon=ft.Icons.EDIT_NOTE,
                                 on_click=on_edit),
            ])

    def on_tap_down(self, event: Any) -> None:
        """Left click: selects right away; if it is the second of a double click, opens."""
        now = time.monotonic()
        double = self._last_tap is not None and now - self._last_tap <= DOUBLE_CLICK_SECONDS
        # After a double click, the next click starts counting again (3 quick clicks
        # do not open the window twice).
        self._last_tap = None if double else now
        if double:
            self.on_open(event)
        else:
            self.on_select(event)

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        # The border is always there (transparent): selecting does not change the card size.
        self.frame.bgcolor = ft.Colors.INDIGO_100 if selected else None
        self.frame.border = ft.Border.all(
            2, ft.Colors.INDIGO_400 if selected else ft.Colors.TRANSPARENT)


def details_rows(book: LibraryBook) -> list[tuple[str, str]]:
    """The fields of the book that are filled in, in display order."""
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
    """Details window: big cover, all the data, 'Abrir livro' (reads the PDF in the app)
    and the small button next to the title to rename the book."""

    def __init__(self, book: LibraryBook, cover: bytes | None, library: Path,
                 on_open: Callable[[LibraryBook, Path | None], Awaitable[None]],
                 on_close: Callable[[Any], None],
                 on_rename: Callable[[LibraryBook, str], Awaitable[bool]],
                 update: Callable[[], None]) -> None:
        self.book = book
        self.on_open, self.on_rename, self.update = on_open, on_rename, update
        # expand_loose: the title takes only the width it needs (the pencil stays next to it),
        # but long titles still wrap instead of overflowing the window.
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
        self.main_file = main_file = book.main_file(library)
        self.dialog = ft.AlertDialog(
            title=self.title_row,
            content=ft.Container(width=660, height=340, content=ft.Row(controls=[
                cover_view(book, cover, big=True),
                ft.Column(controls=self._info(), scroll=ft.ScrollMode.AUTO, expand=True,
                          spacing=6),
            ], vertical_alignment=ft.CrossAxisAlignment.START, spacing=18)),
            actions=[
                ft.FilledButton("Abrir livro", icon=ft.Icons.MENU_BOOK,
                                on_click=self.open_book, disabled=main_file is None),
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

    async def open_book(self, _event: Any) -> None:
        """PDFs open in the app's reader (the gallery decides)."""
        await self.on_open(self.book, self.main_file)

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
