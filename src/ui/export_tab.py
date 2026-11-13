"""Exportar tab: copies books of the open library to another folder."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

import flet as ft

from ..core.files import latest_manifest, undo_manifest
from ..core.models import Status
from ..core.settings import Settings
from ..exporting import exporter
from ..library.database import LibraryBook
from ..library.search import search
from .widgets import (STATUS_COLORS, TAB_GALLERY, page_count, pager_controls, section,
                      update_pager)

if TYPE_CHECKING:  # for the editor only; avoids a circular import
    from .app import PersonalLibraryApp

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


class ExportTab:
    """Selection of library books, destination, layout and the export actions."""

    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        settings = app.settings
        self.selected: set[int] = set()  # ids of ticked books
        self.results: dict[int, tuple[Status, str]] = {}  # result by book id
        self.page_index = 0
        self._known_ids: set[int] = set()
        self.search_field = ft.TextField(
            hint_text="Filtrar por título, autor, etiqueta…", prefix_icon=ft.Icons.SEARCH,
            dense=True, expand=True, on_change=self.on_search)
        self.summary = ft.Text(weight=ft.FontWeight.BOLD)
        self.list_view = ft.ListView(controls=[], spacing=2, expand=True)
        self.empty = ft.Column(controls=[
            ft.Text("Escolha a biblioteca (aba Galeria ou Importar) para ver os livros que podem "
                    "ser exportados.", size=13, color=ft.Colors.GREY_700),
            ft.OutlinedButton("Abrir a Galeria", icon=ft.Icons.COLLECTIONS_BOOKMARK,
                              on_click=self.on_go_gallery),
        ])
        self.prev_btn, self.page_label, self.next_btn = pager_controls(self.on_prev, self.on_next)
        self.dest_field = ft.TextField(label="Pasta de destino", value=settings.destination,
                                       dense=True, expand=True)
        self.cb_folder = ft.Checkbox(label="Uma pasta por livro (Autor/Título)",
                                     value=settings.export_folder_per_book)
        self.cb_opf = ft.Checkbox(label="Arquivo .opf com os metadados", value=settings.export_opf)
        self.cb_cover = ft.Checkbox(label="Capa (cover.jpg)", value=settings.export_cover)
        self.btn_dry = ft.OutlinedButton("Simular", icon=ft.Icons.VISIBILITY,
                                         on_click=self.on_dry_run)
        self.btn_export = ft.FilledButton("Exportar", icon=ft.Icons.IOS_SHARE,
                                          on_click=self.on_export)
        self.btn_undo = ft.OutlinedButton("Desfazer última", icon=ft.Icons.UNDO,
                                          on_click=self.on_undo)
        app.register_actions(self.btn_dry, self.btn_export, self.btn_undo)

    def build(self) -> ft.Control:
        dest_row = ft.Row(controls=[
            self.dest_field,
            ft.OutlinedButton("Escolher…", icon=ft.Icons.FOLDER_OPEN,
                              on_click=self.on_pick_destination),
        ])
        select_row = ft.Row(controls=[
            self.search_field,
            ft.TextButton("Marcar todos", on_click=lambda _e: self.select_all(True)),
            ft.TextButton("Desmarcar todos", on_click=lambda _e: self.select_all(False)),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER)
        self.body = ft.Column(controls=[self.empty], expand=True)
        pager = ft.Row(controls=[self.prev_btn, self.page_label, self.next_btn], spacing=12)
        left = section("Livros da biblioteca", select_row, self.summary, self.body, pager,
                       expand=True)
        hint = ft.Text("Uma pasta comum (pen drive, backup, outro computador). Para colocar "
                       "livros numa biblioteca use a aba Importar.", size=11,
                       color=ft.Colors.GREY_700)
        settings = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=10, expand=True, controls=[
            section("Destino", dest_row, hint),
            section("Formato", self.cb_folder, self.cb_opf, self.cb_cover, ft.Text(
                "A pasta exportada pode ser adicionada em outra biblioteca com 'Adicionar de "
                "pastas e subpastas'.", size=11, color=ft.Colors.GREY_700)),
        ])
        # Buttons outside the scroll area: always visible, even in short windows.
        buttons = ft.Row(controls=[self.btn_dry, self.btn_export, self.btn_undo], spacing=8)
        right = ft.Column(width=460, spacing=10, controls=[settings, buttons])
        return ft.Container(padding=12, expand=True, content=ft.Row(
            controls=[left, right], expand=True, spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.START))

    def store(self, settings: Settings) -> None:
        settings.destination = (self.dest_field.value or "").strip()
        settings.export_folder_per_book = bool(self.cb_folder.value)
        settings.export_opf = bool(self.cb_opf.value)
        settings.export_cover = bool(self.cb_cover.value)

    def options(self, dry_run: bool = False) -> exporter.ExportOptions:
        return exporter.ExportOptions(folder_per_book=bool(self.cb_folder.value),
                                      write_opf=bool(self.cb_opf.value),
                                      include_cover=bool(self.cb_cover.value), dry_run=dry_run)

    # ------------------------------------------------------------------ list and selection

    def on_library_changed(self, changed: bool) -> None:
        """Another library: everything ticked. The same one reloaded: keeps the selection and
        ticks the new books."""
        ids = {book.id for book in self.app.books}
        if changed:
            self.selected, self.results = set(ids), {}
        else:
            self.selected = (self.selected & ids) | (ids - self._known_ids)
        self._known_ids = ids
        self.page_index = 0
        self.refresh()

    def visible_books(self) -> list[LibraryBook]:
        return search(self.app.books, self.search_field.value or "") \
            if self.app.library is not None else []

    def _row(self, book: LibraryBook) -> ft.Control:
        status, message = self.results.get(book.id, (None, ""))
        detail = ", ".join(sorted(book.formats)) or "sem arquivo"
        if message:
            detail += f" · {message}"
        controls: list[ft.Control] = [
            ft.Checkbox(value=book.id in self.selected,
                        on_change=lambda e, item=book: self.toggle(item, bool(e.control.value))),
            ft.Column(controls=[
                ft.Text(f"{book.title} — {book.authors_text}", size=13, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(detail, size=11, color=ft.Colors.GREY_600, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=0, expand=True),
        ]
        if status is not None:
            controls.append(ft.Text(status.value, color=STATUS_COLORS[status],
                                    weight=ft.FontWeight.BOLD, size=12, width=80))
        return ft.Row(controls=controls, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def toggle(self, book: LibraryBook, value: bool) -> None:
        (self.selected.add if value else self.selected.discard)(book.id)
        self._refresh_summary()
        self.app.page.update()

    def select_all(self, value: bool) -> None:
        """Ticks/unticks the books of the current filter (or all of them, with no filter)."""
        ids = {book.id for book in self.visible_books()}
        self.selected = self.selected | ids if value else self.selected - ids
        self.refresh()

    def _refresh_summary(self) -> None:
        if self.app.library is None:
            self.summary.value = ""
            return
        total, visible = len(self.app.books), len(self.visible_books())
        text = f"{len(self.selected)} de {total} livro(s) marcados para exportar"
        if visible != total:
            text += f" · {visible} no filtro"
        done = sum(1 for status, _m in self.results.values() if status is Status.DONE)
        if done:
            text += f" · {done} exportado(s)"
        self.summary.value = text

    def refresh(self) -> None:
        books = self.visible_books()
        pages = page_count(len(books), PAGE_SIZE)
        self.page_index = min(self.page_index, pages - 1)
        start = self.page_index * PAGE_SIZE
        self.list_view.controls = [self._row(book) for book in books[start:start + PAGE_SIZE]]
        self.body.controls = [self.list_view] if self.app.library is not None else [self.empty]
        update_pager(self.prev_btn, self.page_label, self.next_btn, self.page_index, pages)
        self._refresh_summary()
        self.app.page.update()

    def on_search(self, _event: Any) -> None:
        self.page_index = 0
        self.refresh()

    def on_prev(self, _event: Any) -> None:
        self.page_index = max(0, self.page_index - 1)
        self.refresh()

    def on_next(self, _event: Any) -> None:
        self.page_index += 1
        self.refresh()

    async def on_go_gallery(self, _event: Any) -> None:
        await self.app.go_to_tab(TAB_GALLERY)

    async def on_pick_destination(self, _event: Any) -> None:
        folder = await self.app.pick_directory("Escolha a pasta de destino")
        if folder:
            self.dest_field.value = folder
            self.app.save()
            self.app.page.update()

    # ------------------------------------------------------------------ actions

    async def on_dry_run(self, _event: Any) -> None:
        await self._export(dry_run=True)

    async def on_export(self, _event: Any) -> None:
        await self._export(dry_run=False)

    async def _export(self, dry_run: bool) -> None:
        if self.app.library is None:
            self.app.log("Escolha a biblioteca antes de exportar.", True)
            return
        books = [book for book in self.app.books if book.id in self.selected]
        if not books:
            self.app.log("Marque ao menos um livro para exportar.", True)
            return
        dest = (self.dest_field.value or "").strip()
        if not dest:
            self.app.log("Informe a pasta de destino.", True)
            return
        self.app.save()
        try:
            report, items = await self.app.run_job(
                exporter.export_books, books, self.app.library, Path(dest),
                self.options(dry_run), label="Simulando" if dry_run else "Exportando")
        except Exception as exc:
            logger.exception("Export failed")
            self.app.log(f"Erro ao exportar: {exc}", True)
            return
        for item in items:
            if dry_run and item.status is Status.READY:
                target = item.target.relative_to(dest) if item.target else ""
                self.results[item.book.id] = (Status.READY, f"iria para {target}")
            else:
                self.results[item.book.id] = (item.status, item.message)
        self.app.log_errors(report.errors)
        if report.manifest:
            self.app.log(f"Registro para desfazer: {report.manifest}")
        verb = "seriam exportados" if dry_run else "exportados"
        message = f"{'Simulação: ' if dry_run else ''}{report.done} livro(s) {verb} para {dest}"
        if report.skipped:
            message += f" · {report.skipped} já estavam lá ou sem arquivo"
        if report.failed:
            message += f" · {report.failed} com erro"
        self.app.log(message + ".", error=bool(report.failed))
        self.refresh()

    async def on_undo(self, _event: Any) -> None:
        dest = (self.dest_field.value or "").strip()
        manifest = latest_manifest(Path(dest)) if dest else None
        if manifest is None:
            self.app.log("Não há exportação para desfazer neste destino.", True)
            return
        try:
            report = await self.app.run_job(undo_manifest, manifest, label="Desfazendo",
                                            cancellable=False)
        except Exception as exc:
            logger.exception("Undo failed")
            self.app.log(f"Erro ao desfazer: {exc}", True)
            return
        self.app.log_errors(report.errors)
        self.app.log(f"Exportação desfeita: {report.done} de {report.total} livros.",
                     error=bool(report.failed))
        self.results.clear()
        self.refresh()
