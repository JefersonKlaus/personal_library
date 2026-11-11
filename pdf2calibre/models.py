"""Estruturas de dados compartilhadas por todo o organizador."""
from __future__ import annotations

import enum
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any


class Status(str, enum.Enum):
    """Situação de um livro durante a análise e a organização."""

    READY = "pronto"
    WARNING = "atenção"
    DUPLICATE = "duplicado"
    EXISTS = "já existe"
    ERROR = "erro"
    DONE = "concluído"
    FAILED = "falhou"


class Mode(str, enum.Enum):
    """Como os arquivos chegam ao destino."""

    COPY = "copiar"
    MOVE = "mover"


# Só livros nestes estados entram na organização.
USABLE_STATUSES = (Status.READY, Status.WARNING)


@dataclass
class BookEntry:
    """Um PDF analisado, com os metadados que o Calibre vai receber."""

    source: Path
    title: str = ""
    author: str = ""
    year: int | None = None
    language: str | None = None
    pages: int = 0
    size: int = 0
    sha256: str = ""
    status: Status = Status.READY
    selected: bool = True
    notes: list[str] = field(default_factory=list)
    title_origin: str = "arquivo"
    author_origin: str = "arquivo"
    target_dir: Path | None = None
    target_file: Path | None = None

    @property
    def usable(self) -> bool:
        """True se o livro está marcado e em condições de ser organizado."""
        return self.selected and self.status in USABLE_STATUSES

    @property
    def authors(self) -> list[str]:
        """Lista de autores (o campo `author` guarda 'A & B')."""
        return [name.strip() for name in self.author.split("&") if name.strip()]

    def note(self, message: str) -> None:
        """Adiciona uma observação sem repetir as existentes."""
        if message not in self.notes:
            self.notes.append(message)

    def fail(self, message: str, status: Status = Status.ERROR) -> None:
        """Tira o livro da organização registrando o motivo."""
        self.status = status
        self.selected = False
        self.note(message)


@dataclass
class Options:
    """Configurações escolhidas pelo usuário."""

    recursive: bool = True
    folder_per_book: bool = True  # Autor/Título/arquivo.pdf, como o Calibre
    write_opf: bool = True
    extract_cover: bool = False
    mode: Mode = Mode.COPY
    skip_duplicates: bool = True
    verify_hash: bool = True
    prefer_pdf_metadata: bool = True
    author_first: bool = True  # "Autor - Título" no nome do arquivo
    unknown_author: str = "Unknown"
    tags: list[str] = field(default_factory=list)
    max_name_length: int = 80
    dry_run: bool = False
    workers: int = 4

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Options":
        """Cria a partir de um dicionário, ignorando chaves desconhecidas."""
        known = {f.name for f in fields(cls)}
        clean = {key: value for key, value in data.items() if key in known}
        if "mode" in clean:
            try:
                clean["mode"] = Mode(clean["mode"])
            except ValueError:
                del clean["mode"]
        if "tags" in clean and not isinstance(clean["tags"], list):
            del clean["tags"]
        return cls(**clean)


@dataclass
class OperationRecord:
    """Uma operação feita no disco; permite desfazer depois."""

    source: str
    target: str
    mode: str
    sidecars: list[str] = field(default_factory=list)
    created_dirs: list[str] = field(default_factory=list)


@dataclass
class Report:
    """Resultado de uma organização (ou de um desfazer)."""

    total: int = 0
    done: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    dry_run: bool = False
    manifest: Path | None = None
    operations: list[OperationRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        prefix = "Simulação: " if self.dry_run else ""
        text = f"{prefix}{self.done} de {self.total} livros processados"
        if self.skipped:
            text += f", {self.skipped} ignorados"
        if self.failed:
            text += f", {self.failed} com erro"
        if self.cancelled:
            text += " (cancelado)"
        return text + "."
