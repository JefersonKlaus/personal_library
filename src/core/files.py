"""File operations: verified copy, free disk space, undo, and opening a file with the
default program of the system.

Undo uses a "manifest": the list of what was created, written in the destination.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

MANIFEST_DIR = ".personal_library"
ProgressFn = Callable[[int, int, str], None]


def open_with_system(path: Path) -> None:
    """Opens a file or folder with the default program of the system."""
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class FileOperationError(Exception):
    """Expected error while writing files (space, verification, invalid destination)."""


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """SHA-256 hash of the file, read in blocks."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_verified(source: Path, target: Path, expected_sha256: str | None = None) -> None:
    """Copies and checks size and content. On error, leaves no copy behind."""
    try:
        shutil.copy2(source, target)
        if target.stat().st_size != source.stat().st_size:
            raise FileOperationError(f"o tamanho de {source.name} mudou ao copiar")
        if sha256_file(target) != (expected_sha256 or sha256_file(source)):
            raise FileOperationError(f"{source.name} ficou diferente da original (foi alterado?)")
    except Exception:
        target.unlink(missing_ok=True)
        raise


def ensure_free_space(folder: Path, needed: int) -> None:
    free = shutil.disk_usage(folder).free
    if needed * 1.02 > free:
        raise FileOperationError(
            f"Espaço insuficiente: precisa de {needed / 1e6:.0f} MB e há {free / 1e6:.0f} MB livres.")


def make_dirs(path: Path) -> list[str]:
    """Creates the folder and returns the new folders (outermost to innermost)."""
    missing: list[Path] = []
    current = path
    while not current.exists():
        missing.append(current)
        current = current.parent
    path.mkdir(parents=True, exist_ok=True)
    return [str(item) for item in reversed(missing)]


def remove_empty_dirs(created: list[str]) -> None:
    """Deletes the created folders, innermost first, while they are empty."""
    for directory in reversed(created):
        try:
            Path(directory).rmdir()
        except OSError:
            break  # not empty (or gone): stop going up


# ---------------------------------------------------------------- undo

@dataclass
class CreatedFiles:
    """What an operation created on disk (so it can be undone)."""

    files: list[str] = field(default_factory=list)
    created_dirs: list[str] = field(default_factory=list)


@dataclass
class UndoReport:
    total: int = 0
    done: int = 0
    failed: int = 0
    errors: list[str] = field(default_factory=list)


def write_manifest(dest_root: Path, records: list[CreatedFiles]) -> Path:
    folder = Path(dest_root) / MANIFEST_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"manifest-{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    payload = {"version": 2, "created": datetime.now().isoformat(timespec="seconds"),
               "records": [asdict(record) for record in records]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def latest_manifest(dest_root: Path) -> Path | None:
    """Latest record in this destination that was not undone yet, or None."""
    folder = Path(dest_root) / MANIFEST_DIR
    if not folder.is_dir():
        return None
    candidates = [item for item in folder.glob("manifest-*.json")
                  if not item.name.endswith(".undone.json")]
    return max(candidates, key=lambda item: item.name, default=None)


def undo_manifest(manifest: Path, progress: ProgressFn | None = None) -> UndoReport:
    """Deletes what was created (files and empty folders)."""
    manifest = Path(manifest)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    records = [CreatedFiles(**item) for item in data.get("records", [])]
    report = UndoReport(total=len(records))
    for index, record in enumerate(reversed(records), start=1):
        name = Path(record.files[0]).name if record.files else "?"
        try:
            for file in record.files:
                Path(file).unlink(missing_ok=True)
            remove_empty_dirs(record.created_dirs)
            report.done += 1
        except OSError as exc:
            report.failed += 1
            report.errors.append(f"{name}: {exc}")
        if progress:
            progress(index, report.total, name)
    if report.failed == 0:
        manifest.rename(manifest.with_suffix(".undone.json"))
    return report
