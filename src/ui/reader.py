"""Reading a PDF one page at a time (Galeria > details > Abrir livro).

Normally the reader has a window of its own (reader_window.py), which can be maximized,
minimized, resized or closed without blocking the app. When that is not possible (the
web version) it takes the place of the tabs in the main window instead.

Pages turn with the buttons, by typing the page number, or with the keyboard: → ↓ Page
Down and space go forward, ← ↑ Page Up go back, Home/End go to the first/last page and
Esc closes. Each page is rendered in a background thread; the next one is prepared while
the current one is read, and a quick series of clicks only shows the last page asked
for."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

import flet as ft

from ..pdf.pdf_pages import PdfPages

logger = logging.getLogger(__name__)

NEXT_KEYS = {"Arrow Right", "Arrow Down", "Page Down", " "}
PREVIOUS_KEYS = {"Arrow Left", "Arrow Up", "Page Up"}


class ReaderView:
    """One open PDF; `control` is the whole reader.

    `own_window`: the reader is alone in its window, so there is no "back to the gallery"
    arrow (the window has its own close button) and `on_close` closes the window."""

    def __init__(self, title: str, pages: PdfPages,
                 on_close: Callable[[], Awaitable[None]],
                 open_external: Callable[[Path], None], update: Callable[[], None],
                 own_window: bool = False) -> None:
        self.title, self.pages = title, pages
        self.on_close, self.open_external, self.update = on_close, open_external, update
        self.index = 0
        self._seq = 0  # drops renders that went stale (the user kept turning pages)
        self._tasks: set[asyncio.Task[None]] = set()  # prefetches (kept until they end)
        self._typing = False  # the page number field has the focus: keys are for it
        count = pages.page_count
        self.image = ft.Image(src=b"", fit=ft.BoxFit.CONTAIN, gapless_playback=True,
                              expand=True, visible=False)
        self.loading = ft.ProgressRing(width=36, height=36)
        self.message = ft.Text(size=13, color=ft.Colors.RED_700, visible=False,
                               text_align=ft.TextAlign.CENTER)
        self.page_field = ft.TextField(value="1", width=72, dense=True,
                                       text_align=ft.TextAlign.CENTER,
                                       on_submit=self.on_page_submit,
                                       on_focus=self._focus(True), on_blur=self._focus(False))
        self.count_text = ft.Text(f"de {count}", size=14)
        self.btn_first = self._button(ft.Icons.FIRST_PAGE, "Primeira página", self.on_first)
        self.btn_prev = self._button(ft.Icons.CHEVRON_LEFT, "Página anterior (←)", self.on_prev)
        self.btn_next = self._button(ft.Icons.CHEVRON_RIGHT, "Próxima página (→)", self.on_next)
        self.btn_last = self._button(ft.Icons.LAST_PAGE, "Última página", self.on_last)
        back = [] if own_window else [
            ft.IconButton(icon=ft.Icons.ARROW_BACK, tooltip="Voltar à galeria (Esc)",
                          on_click=self.on_back)]
        toolbar = ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=[
            *back,
            ft.Text(title, size=16, weight=ft.FontWeight.BOLD, expand=True, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS),
            ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="Abrir no programa padrão",
                          on_click=lambda _e: self.open_external(pages.path)),
        ])
        pager = ft.Row(alignment=ft.MainAxisAlignment.CENTER,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER,
                       controls=[self.btn_first, self.btn_prev, ft.Text("Página", size=14),
                                 self.page_field, self.count_text, self.btn_next,
                                 self.btn_last])
        sheet = ft.Container(
            expand=True, bgcolor=ft.Colors.GREY_200, border_radius=8, padding=8,
            alignment=ft.Alignment.CENTER,
            content=ft.Stack(expand=True, alignment=ft.Alignment.CENTER,
                             controls=[self.image, self.loading, self.message]))
        self.control = ft.Column(expand=True, spacing=8, controls=[toolbar, sheet, pager])
        self._refresh_pager()

    @staticmethod
    def _button(icon: Any, tooltip: str, handler: Callable[[Any], Any]) -> ft.IconButton:
        return ft.IconButton(icon=icon, tooltip=tooltip, on_click=handler)

    def _focus(self, typing: bool) -> Callable[[Any], None]:
        def handler(_event: Any) -> None:
            self._typing = typing
        return handler

    def _refresh_pager(self) -> None:
        last = self.pages.page_count - 1
        self.page_field.value = str(self.index + 1)
        self.btn_first.disabled = self.btn_prev.disabled = self.index == 0
        self.btn_next.disabled = self.btn_last.disabled = self.index == last

    # ------------------------------------------------------------------ showing a page

    async def show(self, index: int) -> None:
        """Shows the page (from 0; out of range is clamped) and prepares the next one."""
        index = max(0, min(self.pages.page_count - 1, index))
        self.index = index
        self._seq += 1
        seq = self._seq
        self._refresh_pager()
        self.message.visible = False
        self.loading.visible = not self.pages.is_ready(index)
        self.update()
        data, error = None, ""
        try:
            data = await asyncio.to_thread(self.pages.render, index)
        except Exception as exc:  # a broken page: the others can still be read
            logger.warning("Could not render page %s of %s: %s", index + 1,
                           self.pages.path, exc)
            error = str(exc) or type(exc).__name__
        if seq != self._seq:  # the user already asked for another page
            return
        self.loading.visible = False
        if data is None:
            self.image.visible = False
            self.message.value = f"Não foi possível mostrar a página {index + 1}: {error}"
            self.message.visible = True
        else:
            self.image.src, self.image.visible = data, True
        self.update()
        if index + 1 < self.pages.page_count and not self.pages.is_ready(index + 1):
            task = asyncio.create_task(self._prefetch(index + 1))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _prefetch(self, index: int) -> None:
        try:
            await asyncio.to_thread(self.pages.render, index)
        except Exception:  # shown (with the message) if the user goes there
            logger.debug("prefetch of page %s failed", index + 1, exc_info=True)

    # ------------------------------------------------------------------ events

    async def on_first(self, _event: Any) -> None:
        await self.show(0)

    async def on_prev(self, _event: Any) -> None:
        await self.show(self.index - 1)

    async def on_next(self, _event: Any) -> None:
        await self.show(self.index + 1)

    async def on_last(self, _event: Any) -> None:
        await self.show(self.pages.page_count - 1)

    async def on_back(self, _event: Any) -> None:
        await self.on_close()

    async def on_page_submit(self, _event: Any) -> None:
        text = (self.page_field.value or "").strip()
        if text.isdigit():
            await self.show(int(text) - 1)
        else:  # not a number: back to the current page
            self._refresh_pager()
            self.update()

    async def on_key(self, event: Any) -> None:
        """page.on_keyboard_event while the reader is open."""
        if self._typing:  # arrows and Home/End move the cursor in the page field
            return
        key = event.key
        if key in NEXT_KEYS:
            await self.show(self.index + 1)
        elif key in PREVIOUS_KEYS:
            await self.show(self.index - 1)
        elif key == "Home":
            await self.show(0)
        elif key == "End":
            await self.show(self.pages.page_count - 1)
        elif key == "Escape":
            await self.on_close()
