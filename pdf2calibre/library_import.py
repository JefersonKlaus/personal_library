"""Importar: coloca os PDFs revisados na biblioteca do Calibre (a mesma da Galeria).

O Calibre é o dono da biblioteca: copiar arquivos direto para a pasta dele não
funciona (ele só enxerga o que está no metadata.db). Por isso cada livro é
preparado numa pasta temporária (`Título - Autor.pdf` + `.opf` + capa) e
adicionado com `calibredb add`, que lê todos os metadados do OPF. Os ids criados
ficam registrados para o "Desfazer última importação".
"""
from __future__ import annotations

import dataclasses
import json
import logging
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import calibre, organizer, planner
from .library import LibraryError, load_library
from .models import BookEntry, Mode, Options, Status
from .settings import CONFIG_DIR

logger = logging.getLogger(__name__)

IMPORTS_DIR = CONFIG_DIR / "imports"
ProgressFn = Callable[[int, int, str], None]


@dataclass
class ImportReport:
    """Resultado de uma importação para a biblioteca."""

    total: int = 0
    added: int = 0
    existing: int = 0
    failed: int = 0
    cancelled: bool = False
    book_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    record: Path | None = None

    def summary(self) -> str:
        text = f"{self.added} de {self.total} livro(s) adicionados à biblioteca"
        if self.existing:
            text += f", {self.existing} já estavam nela"
        if self.failed:
            text += f", {self.failed} com erro"
        if self.cancelled:
            text += " (cancelado)"
        return text + "."


def import_to_library(entries: list[BookEntry], library: Path, options: Options,
                      calibredb: Path, progress: ProgressFn | None = None,
                      cancel: threading.Event | None = None,
                      records_dir: Path = IMPORTS_DIR) -> ImportReport:
    """Adiciona os livros marcados à biblioteca e atualiza a situação de cada um."""
    library = Path(library)
    todo = [entry for entry in entries if entry.usable]
    report = ImportReport(total=len(todo))
    if not todo:
        return report
    if options.skip_duplicates:
        report.existing += _skip_volumes_already_in_library(todo, library)
        todo = [entry for entry in todo if entry.usable]
        if not todo:
            return report
    # A capa sai sempre da 1ª página: com o OPF o Calibre não gera uma sozinho.
    staging_options = dataclasses.replace(
        options, folder_per_book=True, write_opf=True, extract_cover=True,
        mode=Mode.COPY, dry_run=False)
    total = len(todo)

    def step(prefix: str, offset: int) -> ProgressFn:
        def report_progress(done: int, _total: int, message: str) -> None:
            if progress:
                progress(offset + done, total * 2, f"{prefix} {message}")
        return report_progress

    staging = Path(tempfile.mkdtemp(prefix="personal-library-"))
    try:
        planner.assign_targets(todo, staging, staging_options)
        organizer.organize(todo, staging, staging_options, step("preparando", 0), cancel)
        ready = [entry for entry in todo if entry.status is Status.DONE]
        results = calibre.import_entries(ready, library, staging_options, calibredb,
                                         step("adicionando", total), cancel)
        finished = {id(result.entry) for result in results}
        for result in results:
            entry = result.entry
            if result.ok:
                report.added += 1
                report.book_ids += result.book_ids
                entry.note(f"na biblioteca (id {', '.join(map(str, result.book_ids))})")
            elif result.duplicate:
                report.existing += 1
                entry.status = Status.EXISTS
                entry.note("já existe na biblioteca")
            else:
                report.failed += 1
                entry.fail(result.message, Status.FAILED)
                report.errors.append(f"{entry.title}: {result.message}")
        for entry in ready:  # cancelado antes de chegar ao calibredb
            if id(entry) not in finished:
                entry.status = Status.READY
        staged = {id(entry) for entry in ready}
        for entry in todo:  # falhou já na preparação (arquivo sumiu, disco cheio...)
            if entry.status is Status.FAILED and id(entry) not in staged:
                report.failed += 1
                report.errors.append(f"{entry.title}: {entry.notes[-1] if entry.notes else ''}")
        report.cancelled = bool(cancel is not None and cancel.is_set())
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        for entry in todo:  # a pasta temporária não existe mais
            entry.target_dir = entry.target_file = None
    if report.book_ids:
        report.record = write_import_record(records_dir, library, report.book_ids,
                                            [e.title for e in todo if e.status is Status.DONE])
    return report


def _skip_volumes_already_in_library(entries: list[BookEntry], library: Path) -> int:
    """Volumes vão com --duplicates (o Calibre só compara título + autor), então quem
    evita importar o mesmo volume duas vezes é o app: título + autor + série + volume."""
    volumes = [e for e in entries if e.series and e.series_index is not None]
    if not volumes:
        return 0
    try:
        existing = {planner.book_key(b.title, b.authors, b.series, b.series_index)
                    for b in load_library(library)}
    except LibraryError as exc:
        logger.warning("Não foi possível conferir duplicados em %s: %s", library, exc)
        return 0
    skipped = 0
    for entry in volumes:
        key = planner.book_key(entry.title, entry.authors or [entry.author], entry.series,
                               entry.series_index)
        if key in existing:
            entry.fail("já existe na biblioteca (mesmo título, autor e volume)", Status.EXISTS)
            skipped += 1
    return skipped


# ---------------------------------------------------------------- desfazer

def write_import_record(folder: Path, library: Path, ids: list[int], titles: list[str]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"import-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    payload = {"version": 1, "created": datetime.now().isoformat(timespec="seconds"),
               "library": str(Path(library).resolve()), "ids": ids, "titles": titles}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_import(library: Path, folder: Path = IMPORTS_DIR) -> Path | None:
    """Última importação ainda não desfeita nesta biblioteca."""
    if not folder.is_dir():
        return None
    target = str(Path(library).resolve())
    for path in sorted(folder.glob("import-*.json"), key=lambda p: p.name, reverse=True):
        if path.name.endswith(".undone.json"):
            continue
        try:
            if json.loads(path.read_text(encoding="utf-8")).get("library") == target:
                return path
        except (OSError, ValueError):
            continue
    return None


def undo_import(record: Path, calibredb: Path) -> tuple[int, str]:
    """Remove os livros da importação (vão para a lixeira do Calibre).

    Devolve (quantos, mensagem de erro ou "").
    """
    data = json.loads(Path(record).read_text(encoding="utf-8"))
    ids = [int(book_id) for book_id in data.get("ids", [])]
    ok, message = calibre.remove_books(calibredb, Path(data["library"]), ids)
    if not ok:
        return 0, message
    Path(record).rename(Path(record).with_suffix(".undone.json"))
    return len(ids), ""
