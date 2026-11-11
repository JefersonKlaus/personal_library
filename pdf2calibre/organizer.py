"""Execução: copiar/mover os PDFs, gerar OPF e capa, e desfazer a operação."""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from .calibre import find_library_root
from .cover import extract_cover
from .metadata import sha256_file
from .models import BookEntry, Mode, OperationRecord, Options, Report, Status
from .opf import write_opf
from .planner import sidecar_paths

logger = logging.getLogger(__name__)

MANIFEST_DIR = ".pdf2calibre"
ProgressFn = Callable[[int, int, str], None]


class OrganizerError(Exception):
    """Erro esperado durante a organização (espaço, verificação, etc.)."""


def _make_dirs(path: Path) -> list[str]:
    """Cria a pasta e devolve as pastas novas (da mais externa para a interna)."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    return [str(item) for item in reversed(missing)]


def _remove_empty(created: list[str]) -> None:
    for directory in reversed(created):
        try:
            Path(directory).rmdir()
        except OSError:
            break  # não está vazia (ou sumiu): para de subir


def _check_space(dest_root: Path, entries: list[BookEntry]) -> None:
    needed = sum(entry.size for entry in entries)
    free = shutil.disk_usage(dest_root).free
    if needed * 1.02 > free:
        raise OrganizerError(
            f"Espaço insuficiente no destino: precisa de {needed / 1e6:.0f} MB "
            f"e há {free / 1e6:.0f} MB livres."
        )


def _verify(entry: BookEntry, copy_path: Path, options: Options) -> None:
    if copy_path.stat().st_size != entry.size:
        raise OrganizerError("o tamanho mudou após copiar (o arquivo foi alterado?)")
    if options.verify_hash and entry.sha256 and sha256_file(copy_path) != entry.sha256:
        raise OrganizerError("hash diferente após copiar; o arquivo foi alterado ou corrompido")


def _process(entry: BookEntry, options: Options) -> OperationRecord:
    """Copia (ou move) um livro e cria os arquivos auxiliares."""
    source, target = entry.source, entry.target_file
    assert target is not None
    if source.resolve() == target.resolve():
        raise OrganizerError("origem e destino são o mesmo arquivo")

    created = _make_dirs(target.parent)
    temp = target.with_name(target.name + ".part")
    opf_path, cover_path = sidecar_paths(target, options.folder_per_book)
    sidecars: list[str] = []
    try:
        shutil.copy2(source, temp)
        _verify(entry, temp, options)
        # Capa e OPF antes do PDF aparecer com o nome final: a adição automática
        # do Calibre lê o livro ~2 s depois que ele surge na pasta e, sem o OPF
        # ao lado, importaria os metadados "lixo" de dentro do PDF.
        has_cover = options.extract_cover and extract_cover(temp, cover_path)
        if has_cover:
            sidecars.append(str(cover_path))
        if options.write_opf:
            sidecars.append(str(opf_path))  # antes de gravar: uma falha no meio também é limpa
            write_opf(opf_path, entry, options.tags, cover_path.name if has_cover else None)
        os.replace(temp, target)
    except Exception:
        temp.unlink(missing_ok=True)
        for sidecar in sidecars:
            Path(sidecar).unlink(missing_ok=True)
        _remove_empty(created)
        raise

    if options.mode is Mode.MOVE:
        source.unlink()  # só depois de copiar e verificar com sucesso
    return OperationRecord(str(source), str(target), options.mode.value, sidecars, created)


def organize(entries: list[BookEntry], dest_root: Path, options: Options,
             progress: ProgressFn | None = None,
             cancel: threading.Event | None = None) -> Report:
    """Organiza os livros prontos em `dest_root` e devolve um relatório."""
    dest_root = Path(dest_root)
    library = find_library_root(dest_root)
    if library is not None:
        raise OrganizerError(
            f"O destino fica dentro da biblioteca do Calibre ({library}). O Calibre só "
            "conhece os livros registrados no metadata.db: arquivos copiados direto para "
            "lá não aparecem e bagunçam a biblioteca. Escolha outra pasta e importe com "
            "calibredb, 'Adicionar livros' ou a pasta de adição automática do Calibre."
        )
    todo = [entry for entry in entries if entry.usable and entry.target_file]
    report = Report(total=len(todo), dry_run=options.dry_run,
                    skipped=len(entries) - len(todo))
    if not options.dry_run and todo:
        dest_root.mkdir(parents=True, exist_ok=True)
        if options.mode is Mode.COPY:
            _check_space(dest_root, todo)

    for index, entry in enumerate(todo, start=1):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        try:
            if options.dry_run:
                report.done += 1
            else:
                record = _process(entry, options)
                entry.status = Status.DONE
                report.operations.append(record)
                report.done += 1
        except Exception as exc:  # um livro com problema não pode parar o lote
            logger.exception("Falha ao organizar %s", entry.source)
            entry.fail(str(exc) or type(exc).__name__, Status.FAILED)
            report.failed += 1
            report.errors.append(f"{entry.source.name}: {exc}")
        if progress:
            progress(index, report.total, entry.title)

    if report.operations:
        report.manifest = write_manifest(dest_root, report.operations)
    return report


def write_manifest(dest_root: Path, operations: list[OperationRecord]) -> Path:
    """Grava o registro das operações, usado por `undo`."""
    folder = dest_root / MANIFEST_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"manifest-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    payload = {
        "version": 1,
        "created": datetime.now().isoformat(timespec="seconds"),
        "operations": [asdict(operation) for operation in operations],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_manifest(dest_root: Path) -> Path | None:
    """Último registro ainda não desfeito, ou None."""
    folder = Path(dest_root) / MANIFEST_DIR
    if not folder.is_dir():
        return None
    candidates = [item for item in folder.glob("manifest-*.json")
                  if not item.name.endswith(".undone.json")]
    return max(candidates, key=lambda item: item.name, default=None)


def undo(manifest_path: Path, progress: ProgressFn | None = None) -> Report:
    """Desfaz uma organização: apaga as cópias ou devolve os arquivos movidos."""
    manifest_path = Path(manifest_path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    operations = [OperationRecord(**item) for item in data["operations"]]
    report = Report(total=len(operations))

    for index, operation in enumerate(reversed(operations), start=1):
        source, target = Path(operation.source), Path(operation.target)
        try:
            if operation.mode == Mode.MOVE.value:
                if not target.exists():
                    raise OrganizerError("arquivo não está mais no destino")
                if source.exists():
                    raise OrganizerError("já existe um arquivo na origem; nada foi sobrescrito")
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), str(source))
            else:
                target.unlink(missing_ok=True)
            for sidecar in operation.sidecars:
                Path(sidecar).unlink(missing_ok=True)
            _remove_empty(operation.created_dirs)
            report.done += 1
        except Exception as exc:
            report.failed += 1
            report.errors.append(f"{target.name}: {exc}")
        if progress:
            progress(index, report.total, target.name)

    if report.failed == 0:
        manifest_path.rename(manifest_path.with_suffix(".undone.json"))
    return report
