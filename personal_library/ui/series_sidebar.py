"""Barra lateral da Galeria: escolher uma série (ou todas) e renomear uma série."""
from __future__ import annotations

from typing import Any, Awaitable, Callable

import flet as ft

from ..library.database import LibraryBook
from ..library.search import NO_SERIES, series_counts
from ..renamer import titles_like_series
from ..text import fold

SelectFn = Callable[[str | None], Awaitable[None]]  # None = todos os livros
RenameFn = Callable[[str, str, bool], Awaitable[None]]  # (antigo, novo, renomear títulos)


class SeriesSidebar:
    """Lista 'Todos os livros', 'Sem série' e cada série, com o botão de renomear."""

    def __init__(self, page: Any, on_select: SelectFn, on_rename: RenameFn) -> None:
        self.page = page
        self.on_select = on_select
        self.on_rename = on_rename
        self.selected: str | None = None  # None = todos os livros
        self.books: list[LibraryBook] = []
        self.list_view = ft.ListView(controls=[], spacing=2, expand=True)
        self.container = ft.Container(
            width=250, padding=8, bgcolor=ft.Colors.BLUE_GREY_50, border_radius=8,
            content=ft.Column(controls=[ft.Text("Séries", weight=ft.FontWeight.BOLD),
                                        self.list_view], spacing=6, expand=True))

    # ------------------------------------------------------------------ lista

    def refresh(self, books: list[LibraryBook]) -> None:
        """Remonta a lista; se a série escolhida sumiu (renomeada/apagada), volta a 'Todos'."""
        self.books = books
        series = series_counts(books)
        names = {name for name, _count in series}
        no_series = sum(1 for book in books if not book.series)
        if self.selected not in (None, NO_SERIES) and self.selected not in names:
            self.selected = None
        if self.selected == NO_SERIES and not no_series:
            self.selected = None
        rows = [self._row("Todos os livros", None, len(books), ft.Icons.LIBRARY_BOOKS)]
        if no_series:
            rows.append(self._row("Sem série", NO_SERIES, no_series, ft.Icons.LABEL_OUTLINE))
        rows += [self._row(name, name, count) for name, count in series]
        self.list_view.controls = rows

    def _row(self, label: str, value: str | None, count: int,
             icon: str | None = None) -> ft.Control:
        selected = value == self.selected
        controls: list[ft.Control] = []
        if icon:
            controls.append(ft.Icon(icon, size=16, color=ft.Colors.INDIGO_700))
        controls += [
            ft.Text(label, size=13, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    weight=ft.FontWeight.BOLD if selected else None),
            ft.Text(str(count), size=11, color=ft.Colors.GREY_700),
        ]
        if value:  # só séries de verdade podem ser renomeadas
            controls.append(ft.IconButton(
                icon=ft.Icons.EDIT, icon_size=16, tooltip="Renomear série",
                visual_density=ft.VisualDensity.COMPACT, on_click=self._rename_handler(value)))
        return ft.Container(
            content=ft.Row(controls=controls, spacing=6,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(left=8, right=2, top=2, bottom=2), border_radius=6, ink=True,
            bgcolor=ft.Colors.INDIGO_100 if selected else None,
            on_click=self._select_handler(value))

    def _select_handler(self, value: str | None) -> Callable[[Any], Any]:
        async def handler(_event: Any) -> None:  # async def: o Flet só espera funções async
            self.selected = value
            self.refresh(self.books)
            await self.on_select(value)
        return handler

    # ------------------------------------------------------------------ renomear

    def _rename_handler(self, series: str) -> Callable[[Any], Any]:
        def handler(_event: Any) -> None:
            self.page.show_dialog(self._rename_dialog(series))
        return handler

    def _rename_dialog(self, series: str) -> ft.AlertDialog:
        count = sum(1 for book in self.books if book.series == series)
        same_title = titles_like_series(self.books, series)
        others = {fold(name): name for name, _c in series_counts(self.books) if name != series}
        field = ft.TextField(label="Novo nome da série", value=series, dense=True, autofocus=True)
        warning = ft.Text(size=12, color=ft.Colors.ORANGE_800, visible=False)
        titles = ft.Checkbox(
            label=f"Também renomear os títulos iguais a '{series}' ({same_title} livro(s))",
            value=True, visible=same_title > 0)

        def on_change(_event: Any) -> None:
            existing = others.get(fold((field.value or "").strip()))
            warning.value = (f"Já existe a série '{existing}': os livros desta série vão "
                             "para ela." if existing else "")
            warning.visible = bool(existing)
            self.page.update()

        async def confirm(_event: Any) -> None:
            self.page.pop_dialog()
            await self.on_rename(series, field.value or "", bool(titles.value and same_title))

        field.on_change = on_change
        field.on_submit = confirm
        return ft.AlertDialog(
            title=ft.Text("Renomear série"),
            content=ft.Column(tight=True, spacing=10, width=460,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH, controls=[
                ft.Text(f"{count} livro(s) na série '{series}'.", size=12,
                        color=ft.Colors.GREY_700),
                field, titles, warning]),
            actions=[ft.TextButton("Cancelar", on_click=lambda _e: self.page.pop_dialog()),
                     ft.FilledButton("Renomear", icon=ft.Icons.EDIT, on_click=confirm)])
