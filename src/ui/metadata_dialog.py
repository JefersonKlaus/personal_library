"""Dialog "Editar metadados" of the gallery (right button on a book).

* One book: every field filled in and editable, next to the cover and the read-only data.
* Several books: each field has a checkbox; only the ticked fields are written, with the
  same value in every selected book (typing in a field ticks it). A field shows the
  value when all the books share it, otherwise it starts empty ("vários valores").
"""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import flet as ft

from ..library.database import LibraryBook
from ..library.metadata_editor import (FIELDS, SINGLE_BOOK_ONLY, MetadataError, common_text,
                                       validate)
from .book_views import cover_view

LABELS = {
    "title": "Título", "authors": "Autor(es)", "series": "Série", "series_index": "Volume",
    "year": "Ano", "publisher": "Editora", "tags": "Etiquetas", "languages": "Idiomas",
    "identifiers": "Identificadores", "comments": "Descrição",
}
HELP = {
    "authors": "Vários autores: separe com &",
    "tags": "Separadas por vírgula",
    "languages": "Códigos separados por vírgula: pt, en, es...",
    "identifiers": "tipo:valor separados por vírgula (isbn:978...)",
}
MIXED = "(vários valores)"

SaveFn = Callable[[list[LibraryBook], dict[str, str]], Awaitable[None]]


class MetadataDialog:
    """Edits one book or several; `on_save(books, {field: text})` does the writing."""

    def __init__(self, books: list[LibraryBook], cover: bytes | None, on_save: SaveFn,
                 close: Callable[[], None], update: Callable[[], None]) -> None:
        self.books, self.on_save, self.close, self.update = books, on_save, close, update
        self.many = len(books) > 1
        self.keys = [key for key in FIELDS if not (self.many and key in SINGLE_BOOK_ONLY)]
        self.fields: dict[str, ft.TextField] = {key: self._field(key) for key in self.keys}
        self.ticks: dict[str, ft.Checkbox] = {}
        if self.many:
            self.ticks = {key: ft.Checkbox(value=False, tooltip="Gravar este campo")
                          for key in self.keys}
            for key, text_field in self.fields.items():
                text_field.on_change = self._ticker(key)
        self.error = ft.Text(size=12, color=ft.Colors.RED_700, visible=False)
        title = (f"Editar metadados de {len(books)} livros" if self.many
                 else "Editar metadados")
        self.dialog = ft.AlertDialog(
            modal=True, title=ft.Text(title),
            content=self._many_content() if self.many else self._single_content(cover),
            actions=[ft.TextButton("Cancelar", on_click=lambda _e: self.close()),
                     ft.FilledButton("Salvar", icon=ft.Icons.SAVE, on_click=self.save)])

    # ------------------------------------------------------------------ building

    def _field(self, key: str) -> ft.TextField:
        text = common_text(self.books, key)
        options: dict[str, Any] = {}
        if key == "comments":
            options.update(multiline=True, min_lines=4, max_lines=8)
        if key in ("series_index", "year") and not self.many:
            options.update(width=120)  # next to Série / Editora (one book)
        else:
            options.update(expand=True)
        # Label, not hint: a hint only shows once the field is clicked, and an empty field
        # must say whether the books differ or all have it empty.
        label = f"{LABELS[key]} {MIXED}" if text is None else LABELS[key]
        return ft.TextField(label=label, value=text or "", dense=True,
                            helper=HELP.get(key), **options)

    def _ticker(self, key: str) -> Callable[[Any], None]:
        def on_change(_event: Any) -> None:
            if not self.ticks[key].value:
                self.ticks[key].value = True
                self.update()
        return on_change

    def _single_content(self, cover: bytes | None) -> ft.Control:
        book, f = self.books[0], self.fields
        readonly = [("Formatos", ", ".join(sorted(book.formats)) or "—"),
                    ("Adicionado", book.added.strftime("%d/%m/%Y") if book.added else "—"),
                    ("Pasta", book.path or "—")]
        form = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=12, controls=[
            ft.Container(height=2),  # room for the label of the first field (not clipped)
            f["title"], f["authors"],
            ft.Row(controls=[f["series"], f["series_index"]]),
            ft.Row(controls=[f["publisher"], f["year"]]),
            f["tags"], f["languages"], f["identifiers"], f["comments"],
            *[ft.Row(controls=[ft.Text(label, size=12, weight=ft.FontWeight.BOLD, width=90),
                               ft.Text(value, size=12, selectable=True, expand=True)])
              for label, value in readonly],
            self.error,
        ])
        return ft.Container(width=820, height=520, content=ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.START, spacing=18,
            controls=[cover_view(book, cover, big=True), form]))

    def _many_content(self) -> ft.Control:
        rows = [ft.Row(vertical_alignment=ft.CrossAxisAlignment.START,
                       controls=[self.ticks[key], self.fields[key]]) for key in self.keys]
        intro = ft.Text("Marque os campos que vão ser gravados em todos os livros "
                        "selecionados; os outros não mudam. Etiquetas e idiomas substituem "
                        "os que cada livro tinha.", size=12, color=ft.Colors.GREY_700)
        names = ", ".join(book.title for book in self.books[:5])
        more = f" e mais {len(self.books) - 5}" if len(self.books) > 5 else ""
        books = ft.Text(f"Livros: {names}{more}.", size=12, color=ft.Colors.GREY_700,
                        max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
        return ft.Container(width=640, height=520, content=ft.Column(
            scroll=ft.ScrollMode.AUTO, spacing=12,
            controls=[intro, books, ft.Container(height=2), *rows, self.error]))

    # ------------------------------------------------------------------ saving

    def values(self) -> dict[str, str]:
        """What will be written: every field (one book) or the ticked ones (several)."""
        return {key: self.fields[key].value or "" for key in self.keys
                if not self.many or self.ticks[key].value}

    def show_error(self, message: str) -> None:
        self.error.value, self.error.visible = message, True
        self.update()

    async def save(self, _event: Any) -> None:
        values = self.values()
        try:
            validate(values, len(self.books))
        except MetadataError as exc:
            self.show_error(str(exc))  # the dialog stays open to fix the value
            return
        self.close()
        await self.on_save(self.books, values)
