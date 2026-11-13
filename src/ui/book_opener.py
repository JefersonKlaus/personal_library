"""Abrir livro: how a book of the gallery is opened.

* a PDF: in a reader window of its own (reader_launcher.py), so the app is not blocked;
* in the web version, or when that window cannot be started: the reader takes the place
  of the tabs in the app window (Esc or ← goes back);
* other formats, and PDFs the app cannot read (password, damaged): the default program
  of the system.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.files import open_with_system
from ..library.database import LibraryBook
from ..pdf.pdf_pages import PdfOpenError, PdfPages, check_pdf
from .reader import ReaderView
from .reader_launcher import ERRORS_FILE, open_window

if TYPE_CHECKING:  # for the editor only; avoids a circular import
    from .app import PersonalLibraryApp


class BookOpener:
    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app
        self.reader: ReaderView | None = None  # the reader inside the app window, if open

    async def open(self, book: LibraryBook, path: Path | None) -> None:
        if path is None or not path.exists():
            self.app.log("Arquivo não encontrado na biblioteca.", error=True)
            return
        if path.suffix.lower() != ".pdf":
            self.app.log(f"Só PDFs abrem no app: {path.name} foi aberto no programa padrão.")
            self.open_external(path)
            return
        page = self.app.page
        page.pop_dialog()  # the details window
        try:  # checked here, so a bad PDF does not open an empty window
            await asyncio.to_thread(check_pdf, path)
        except PdfOpenError as exc:
            self.app.log(f"'{book.title}' não abre no app ({exc}); foi aberto no programa "
                         "padrão.")
            self.open_external(path)
            return
        if not getattr(page, "web", False) and self._open_window(book, path):
            return
        try:
            await self.open_here(book.title, path)
        except PdfOpenError as exc:  # the file changed since the check
            self.app.log(f"Não foi possível abrir '{book.title}': {exc}", error=True)

    def _open_window(self, book: LibraryBook, path: Path) -> bool:
        """Starts the reader window; False (message shown) when it cannot be started."""
        page = self.app.page
        try:
            process = open_window(path, book.title, getattr(page.window, "height", None))
        except OSError as exc:
            self.app.log(f"Não foi possível abrir uma janela de leitura ({exc}); o livro "
                         "foi aberto aqui mesmo.")
            return False
        self.app.log(f"'{book.title}' aberto em uma janela de leitura.")
        if process is not None:
            page.run_task(self.watch, process, book.title)
        return True

    async def watch(self, process: Any, title: str, seconds: float = 10) -> None:
        """A reader window that fails right away says so, instead of just not appearing
        (it has no console: its error is in ERRORS_FILE)."""
        waited = 0.0
        while process.poll() is None:
            if waited >= seconds:
                return  # still open: the window is up
            await asyncio.sleep(0.2)
            waited += 0.2
        if process.returncode != 0:
            self.app.log(f"A janela de leitura de '{title}' não abriu (erro "
                         f"{process.returncode}). Detalhes em {ERRORS_FILE}.", error=True)

    def open_external(self, path: Path) -> None:
        """Opens the file with the default program of the system."""
        try:
            open_with_system(path)
        except Exception as exc:
            self.app.log(f"Não foi possível abrir {path}: {exc}", error=True)

    # ------------------------------------------------------------------ reader in the app

    async def open_here(self, title: str, path: Path) -> None:
        """The reader in place of the tabs. Raises PdfOpenError (password, damaged file)."""
        pages = await asyncio.to_thread(PdfPages, path)
        await self.close_here()
        self.reader = ReaderView(title, pages, on_close=self.close_here,
                                 open_external=self.open_external, update=self.app.page.update)
        self.app.replace_tabs(self.reader.control)
        await self.reader.show(0)

    async def close_here(self) -> None:
        """Back to the tabs (the gallery as it was) and frees the PDF."""
        reader, self.reader = self.reader, None
        if reader is None:
            return
        self.app.replace_tabs(None)
        await asyncio.to_thread(reader.pages.close)

    async def on_key(self, event: Any) -> None:
        """Keys of the window go to the reader while it is open in the app."""
        if self.reader is not None:
            await self.reader.on_key(event)
