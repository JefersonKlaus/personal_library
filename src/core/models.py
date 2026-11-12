"""Modelo de dados da importação: o livro analisado e as opções da análise."""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


class Status(str, enum.Enum):
    """Situação de um livro durante a análise e a importação/exportação."""

    READY = "pronto"
    WARNING = "atenção"
    DUPLICATE = "duplicado"
    EXISTS = "já existe"
    ERROR = "erro"
    DONE = "concluído"
    FAILED = "falhou"


# Só livros nestes estados são importados.
USABLE_STATUSES = (Status.READY, Status.WARNING)


@dataclass
class BookEntry:
    """Um PDF analisado, com os metadados que a biblioteca vai receber."""

    source: Path
    title: str = ""
    author: str = ""  # vários autores: 'A & B'
    year: int | None = None
    series: str = ""
    series_index: float | None = None  # número do volume na série
    publisher: str = ""
    tags: list[str] = field(default_factory=list)  # do nome do arquivo ou @tags=...
    language: str | None = None
    pages: int = 0
    size: int = 0
    sha256: str = ""
    status: Status = Status.READY
    selected: bool = True
    notes: list[str] = field(default_factory=list)
    title_origin: str = "arquivo"  # arquivo | pdf | fixo | manual
    author_origin: str = "arquivo"

    @property
    def usable(self) -> bool:
        """True se o livro está marcado e em condições de ser importado."""
        return self.selected and self.status in USABLE_STATUSES

    @property
    def authors(self) -> list[str]:
        return [name.strip() for name in self.author.split("&") if name.strip()]

    @property
    def is_volume(self) -> bool:
        return bool(self.series) and self.series_index is not None

    def note(self, message: str) -> None:
        """Adiciona uma observação sem repetir as existentes."""
        if message not in self.notes:
            self.notes.append(message)

    def fail(self, message: str, status: Status = Status.ERROR) -> None:
        """Tira o livro da importação registrando o motivo."""
        self.status = status
        self.selected = False
        self.note(message)


@dataclass
class ImportOptions:
    """Como os PDFs são lidos e importados (aba Importar)."""

    recursive: bool = True
    skip_duplicates: bool = True
    prefer_pdf_metadata: bool = True
    author_first: bool = True  # modo automático: "Autor - Título"
    filename_pattern: str = ""  # "Como importar": "@name - @vol; @auth=ONE"; vazio = automático
    unknown_author: str = "Unknown"
    tags: list[str] = field(default_factory=list)
    workers: int = 4

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImportOptions":
        """Cria a partir de um dicionário, ignorando chaves desconhecidas e tipos errados."""
        defaults = cls()
        clean = {}
        for item in fields(cls):
            value = data.get(item.name)
            if value is not None and isinstance(value, type(getattr(defaults, item.name))):
                clean[item.name] = value
        return cls(**clean)
