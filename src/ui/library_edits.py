"""Changing the library from the gallery (metadata, renaming books and series).

Every change goes through the library tool, with the same steps: find the tool (or say
it is missing), run the change, and report the books that failed. What to change, and
what to do afterwards, stays with the gallery."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Callable

from ..library.cli import LibraryCli
from ..library.manager import PRODUCT
from ..library.metadata_editor import MetadataError
from ..library.renamer import RenameError

if TYPE_CHECKING:  # for the editor only; avoids a circular import
    from .app import PersonalLibraryApp

# Invalid values, with the message ready to be shown.
INVALID = (MetadataError, RenameError)


class LibraryEdits:
    def __init__(self, app: "PersonalLibraryApp") -> None:
        self.app = app

    def tool(self) -> LibraryCli | None:
        """The tool that changes the library, or None (with the message already shown)."""
        if self.app.busy or self.app.library is None:
            return None
        cli = self.app.cli()
        if cli is None:
            self.app.log(f"{PRODUCT} não encontrado: instale-o para alterar a biblioteca.", True)
        return cli

    async def run(self, change: Callable[..., Any], *args: Any, label: str) -> Any | None:
        """Runs `change(cli, library, *args)` book by book, with progress and Cancelar,
        and logs the books that failed. The report, or None if nothing ran."""
        cli = self.tool()
        if cli is None:
            return None
        try:
            report = await self.app.run_job(change, cli, self.app.library, *args, label=label)
        except INVALID as exc:
            self.app.log(str(exc), True)
            return None
        self.app.log_errors(report.errors)
        return report

    async def run_one(self, change: Callable[..., tuple[bool, str]],
                      *args: Any) -> tuple[bool, str] | None:
        """A single quick change (no progress): (ok, error), or None if nothing ran."""
        cli = self.tool()
        if cli is None:
            return None
        self.app.set_busy(True)
        try:
            return await asyncio.to_thread(change, cli, self.app.library, *args)
        except INVALID as exc:
            return False, str(exc)
        finally:
            self.app.set_busy(False)
