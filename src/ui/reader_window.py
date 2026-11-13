"""The reader window: a small Flet app of its own that shows one book, and can be
maximized, minimized, resized or closed without blocking the app.

Started by reader_launcher.py as a separate process (Flet 1.0 has one window per app).
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Awaitable, Callable

import flet as ft

from ..core.files import open_with_system
from ..core.logging_setup import setup_logging
from ..core.paths import LOG_FILE
from ..pdf.pdf_pages import PdfOpenError, PdfPages
from .reader import ReaderView
from .reader_launcher import DEFAULT_HEIGHT, MODULE

logger = logging.getLogger(__name__)


def reader_app(path: Path, title: str, width: int = 0,
               height: int = 0) -> Callable[[ft.Page], Awaitable[None]]:
    """The `main` of the reader window, for `ft.run`."""

    async def main(page: ft.Page) -> None:
        page.title = title
        page.theme_mode = ft.ThemeMode.LIGHT
        page.theme = ft.Theme(color_scheme_seed=ft.Colors.INDIGO)
        page.padding = 8
        try:
            page.window.width, page.window.height = width or 690, height or DEFAULT_HEIGHT
            page.window.min_width, page.window.min_height = 420, 480
        except Exception:  # window not configurable: no problem
            logger.debug("window not configurable", exc_info=True)
        try:
            pages = await asyncio.to_thread(PdfPages, path)
        except PdfOpenError as exc:  # checked by the app already; only if it changed since
            page.add(ft.Text(f"Não foi possível abrir {path.name}: {exc}",
                             color=ft.Colors.RED_700))
            return

        async def close_window() -> None:
            await page.window.close()

        def open_external(file: Path) -> None:
            try:
                open_with_system(file)
            except Exception:
                logger.warning("Could not open %s", file, exc_info=True)

        reader = ReaderView(title, pages, on_close=close_window, open_external=open_external,
                            update=page.update, own_window=True)
        page.on_keyboard_event = reader.on_key
        page.add(reader.control)
        await reader.show(0)

    return main


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=MODULE, description="Janela de leitura de um PDF.")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--title", default="")
    parser.add_argument("--width", type=int, default=0)
    parser.add_argument("--height", type=int, default=0)
    args = parser.parse_args(argv)
    # A log of its own: two processes rotating the same file could lose lines.
    setup_logging(LOG_FILE.with_name("reader.log"))
    ft.run(reader_app(args.pdf, args.title or args.pdf.stem, args.width, args.height),
           no_cdn=True)
    return 0


if __name__ == "__main__":
    sys.exit(run())
