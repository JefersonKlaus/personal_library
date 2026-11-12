"""Escolha da biblioteca: usar uma conhecida, escolher uma pasta ou criar uma nova.

Mostra a linha "Os livros vão para ..." quando há uma biblioteca válida, ou um
aviso com as opções quando não há (ou quando o usuário pede para trocar).
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

import flet as ft

from ..library.cli import LibraryCli
from ..library.location import find_library_in, is_library, known_libraries, new_library_path
from ..library.manager import DATABASE_FILE, PRODUCT

if TYPE_CHECKING:  # só para o editor; evita import circular
    from .app import PersonalLibraryApp

MAX_SUGGESTIONS = 4
IN_USE_HINT = ("Se outro programa estiver usando esta biblioteca (um gerenciador ou leitor de "
               "e-books), feche-o antes de importar.")


class LibraryPicker:
    """Controles e ações para escolher a biblioteca usada pelas três abas."""

    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        self._switching = False  # "Trocar biblioteca…" com uma biblioteca válida
        self.current_text = ft.Text(size=12, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.current_row = ft.Row(controls=[
            ft.Icon(ft.Icons.COLLECTIONS_BOOKMARK, color=ft.Colors.INDIGO_700, size=18),
            ft.Column(controls=[self.current_text, ft.Text(IN_USE_HINT, size=11,
                                                           color=ft.Colors.GREY_700)],
                      spacing=0, expand=True),
            ft.TextButton("Trocar biblioteca…", icon=ft.Icons.SWAP_HORIZ,
                          on_click=self.on_switch),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6)
        self.title = ft.Text(weight=ft.FontWeight.BOLD)
        self.icon = ft.Icon(ft.Icons.WARNING_AMBER)
        self.suggestions = ft.Column(controls=[], spacing=0)
        self.btn_choose = ft.FilledTonalButton("Escolher biblioteca existente…",
                                               icon=ft.Icons.FOLDER_OPEN, on_click=self.on_choose)
        self.btn_create = ft.OutlinedButton("Criar biblioteca nova…",
                                            icon=ft.Icons.CREATE_NEW_FOLDER,
                                            on_click=self.on_create)
        self.btn_cancel = ft.TextButton("Cancelar", on_click=self.on_cancel)
        self.panel = ft.Container(
            visible=False, padding=12, border_radius=8,
            content=ft.Column(spacing=6, controls=[
                ft.Row(controls=[self.icon, self.title],
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Text("Os livros importados vão para uma biblioteca. Escolha uma que você já "
                        "usa ou crie uma nova.", size=12),
                self.suggestions,
                ft.Row(controls=[self.btn_choose, self.btn_create, self.btn_cancel], spacing=8),
            ]))
        app.register_actions(self.btn_choose, self.btn_create)

    @property
    def is_open(self) -> bool:
        return self.panel.visible

    # ------------------------------------------------------------------ estado

    def refresh(self) -> None:
        """Mostra a biblioteca atual, ou o aviso com as opções quando falta uma válida."""
        library = self.app.settings.library
        valid = is_library(library)
        show = not valid or self._switching
        self.panel.visible, self.current_row.visible = show, not show
        self.btn_cancel.visible = valid and self._switching
        self.current_text.value = f"Os livros vão para {library}"
        self.title.value = self._title(library, valid)
        self._style(warning=not valid)
        self.suggestions.controls = self._suggestion_rows(library) if show else []

    @staticmethod
    def _title(library: str, valid: bool) -> str:
        if not library:
            return "Nenhuma biblioteca escolhida ainda."
        if not Path(library).exists():
            return f"A biblioteca escolhida não foi encontrada: {library}"
        if not valid:
            return f"{library} não é uma biblioteca (falta o {DATABASE_FILE})."
        return f"Trocar de biblioteca (atual: {library})"

    def _style(self, warning: bool) -> None:
        """Falta de biblioteca é um aviso; trocar é uma ação normal."""
        self.icon.icon = ft.Icons.WARNING_AMBER if warning else ft.Icons.SWAP_HORIZ
        self.icon.color = ft.Colors.ORANGE_800 if warning else ft.Colors.INDIGO_700
        self.title.color = ft.Colors.ORANGE_900 if warning else ft.Colors.INDIGO_900
        self.panel.bgcolor = ft.Colors.AMBER_50 if warning else ft.Colors.INDIGO_50
        self.panel.border = ft.Border.all(1, ft.Colors.AMBER_300 if warning
                                          else ft.Colors.INDIGO_100)

    def _suggestion_rows(self, library: str) -> list[ft.Control]:
        current = os.path.normcase(os.path.abspath(library)) if library else ""
        found = [path for path in known_libraries()
                 if os.path.normcase(str(path.absolute())) != current][:MAX_SUGGESTIONS]
        rows: list[ft.Control] = []
        if found:
            rows.append(ft.Text(f"Encontradas no seu {PRODUCT}:", size=12,
                                weight=ft.FontWeight.BOLD))
        for path in found:
            rows.append(ft.Row(controls=[
                ft.Icon(ft.Icons.COLLECTIONS_BOOKMARK, size=16, color=ft.Colors.INDIGO_700),
                ft.Text(str(path), size=12, expand=True, selectable=True),
                ft.TextButton("Usar esta", on_click=self._use_handler(path)),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=6))
        return rows

    # ------------------------------------------------------------------ ações

    def _use_handler(self, path: Path) -> Callable[[Any], Any]:
        async def handler(_event: Any) -> None:  # async def: o Flet só espera funções async
            await self.use(path)
        return handler

    async def use(self, path: Path) -> None:
        self._switching = False
        if await self.app.open_library(path):
            self.app.log(f"Biblioteca: {path}. Os livros importados vão para ela.")

    def on_switch(self, _event: Any) -> None:
        self._switching = True
        self.refresh()
        self.app.page.update()

    def on_cancel(self, _event: Any) -> None:
        self._switching = False
        self.refresh()
        self.app.page.update()

    async def on_choose(self, _event: Any) -> None:
        folder = await self.app.pick_directory("Escolha a pasta da biblioteca")
        if not folder:
            return
        found = find_library_in(folder)
        if found is None:
            self.app.log(f"{folder} não é uma biblioteca. Para começar uma nova, use "
                         "Criar biblioteca nova.", True)
            return
        await self.use(found)

    async def on_create(self, _event: Any) -> None:
        """Pergunta onde criar, confirma e cria uma biblioteca vazia."""
        cli = self.app.cli()
        if cli is None:
            self.app.log(f"Para criar uma biblioteca é preciso ter o {PRODUCT} instalado.", True)
            return
        parent = await self.app.pick_directory("Escolha onde criar a biblioteca nova")
        if parent:
            self._confirm_create(new_library_path(Path(parent)), cli)

    def _confirm_create(self, target: Path, cli: LibraryCli) -> None:
        page = self.app.page

        async def create(_event: Any) -> None:
            page.pop_dialog()
            await self.create_at(target, cli)

        page.show_dialog(ft.AlertDialog(
            title=ft.Text("Criar biblioteca"),
            content=ft.Column(tight=True, spacing=8, width=520, controls=[
                ft.Text("A biblioteca nova (vazia) será criada em:"),
                ft.Text(str(target), weight=ft.FontWeight.BOLD, selectable=True),
                ft.Text("Se algum programa estiver usando uma biblioteca de e-books, feche-o "
                        f"antes de continuar. Depois, para abri-la no {PRODUCT}: botão "
                        "Biblioteca > Alternar/criar biblioteca > escolha esta pasta.",
                        size=12, color=ft.Colors.GREY_700),
            ]),
            actions=[ft.TextButton("Cancelar", on_click=lambda _e: page.pop_dialog()),
                     ft.FilledButton("Criar biblioteca", icon=ft.Icons.CREATE_NEW_FOLDER,
                                     on_click=create)]))

    async def create_at(self, target: Path, cli: LibraryCli) -> None:
        self.app.set_busy(True)
        self.app.status_text.value = f"Criando a biblioteca em {target}…"
        self.app.page.update()
        try:
            ok, error = await asyncio.to_thread(cli.create_library, target)
        finally:
            self.app.set_busy(False)
        if not ok:
            self.app.log(f"Não foi possível criar a biblioteca: {error}", True)
            return
        await self.use(target)
        self.app.log(f"Biblioteca criada em {target}. Para vê-la no {PRODUCT}: botão "
                     "Biblioteca > Alternar/criar biblioteca.")
