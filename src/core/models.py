"""Data model of the import: the analysed book and the analysis options."""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


class Status(str, enum.Enum):
    """State of a book during analysis and import/export."""

    READY = "pronto"
    WARNING = "atenção"
    DUPLICATE = "duplicado"
    EXISTS = "já existe"
    ERROR = "erro"
    DONE = "concluído"
    FAILED = "falhou"


# Only books in these states are imported.
USABLE_STATUSES = (Status.READY, Status.WARNING)


@dataclass
class BookEntry:
    """An analysed PDF, with the metadata the library will receive."""

    source: Path
    title: str = ""
    author: str = ""  # several authors: 'A & B'
    year: int | None = None
    series: str = ""
    series_index: float | None = None  # number of the volume in the series
    publisher: str = ""
    tags: list[str] = field(default_factory=list)  # from the file name or @tags=...
    language: str | None = None
    pages: int = 0
    size: int = 0
    sha256: str = ""
    status: Status = Status.READY
    selected: bool = True
    notes: list[str] = field(default_factory=list)
    title_origin: str = "arquivo"  # file | pdf | fixed | manual
    author_origin: str = "arquivo"

    @property
    def usable(self) -> bool:
        """True if the book is ticked and fit to be imported."""
        return self.selected and self.status in USABLE_STATUSES

    @property
    def authors(self) -> list[str]:
        return [name.strip() for name in self.author.split("&") if name.strip()]

    @property
    def is_volume(self) -> bool:
        return bool(self.series) and self.series_index is not None

    def note(self, message: str) -> None:
        """Adds a note without repeating the existing ones."""
        if message not in self.notes:
            self.notes.append(message)

    def fail(self, message: str, status: Status = Status.ERROR) -> None:
        """Takes the book out of the import, recording the reason."""
        self.status = status
        self.selected = False
        self.note(message)


@dataclass
class ImportOptions:
    """How the PDFs are read and imported (Import tab)."""

    recursive: bool = True
    skip_duplicates: bool = True
    prefer_pdf_metadata: bool = True
    author_first: bool = True  # automatic mode: "Autor - Título"
    filename_pattern: str = ""  # "Como importar": "@name - @vol; @auth=ONE"; empty = automatic
    unknown_author: str = "Unknown"
    tags: list[str] = field(default_factory=list)
    workers: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportOptions":
        """Builds from a dict, ignoring unknown keys and wrong types."""
        defaults = cls()
        clean = {}
        for item in fields(cls):
            value = data.get(item.name)
            if value is not None and isinstance(value, type(getattr(defaults, item.name))):
                clean[item.name] = value
        return cls(**clean)
