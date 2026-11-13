"""Analysis of the chosen PDFs: find the files, build each book and mark duplicates.

Priority rules for the metadata of a book:
1. fixed values of "Como importar" (@auth=ONE) beat everything;
2. the file name wins when it follows the user pattern or carries the volume
   (the title inside the PDF, "One Punch Man", would lose the "Vol 18");
3. otherwise, with "Preferir metadados de dentro do PDF", what is in the PDF wins;
4. the PDF always fills in what is still missing (the author, for instance).
"""
from __future__ import annotations

import os
import re
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable

from ..core.files import sha256_file
from ..core.models import USABLE_STATUSES, BookEntry, ImportOptions, Status
from ..core.text import fold, natural_key
from ..parsing.filename_parser import ParsedName
from ..parsing.import_spec import ImportSpec, PatternError, apply_spec, compile_spec
from ..parsing.people import split_authors
from ..parsing.volumes import looks_like_volume
from ..pdf.pdf_reader import PdfInfo, is_junk_author, is_junk_title, looks_like_pdf, read_pdf_info

ProgressFn = Callable[[int, int, str], None]
_SUSPICIOUS_NOTES = ("nome fora do padrão", "o autor", "o título")
# Notes that leave the book with "atenção" (and that the user should check).
WARNING_NOTES = _SUSPICIOUS_NOTES + ("autor não encontrado", "PDF protegido", "mesmo título")


# ---------------------------------------------------------------- files

def find_pdfs(paths: Iterable[Path | str], recursive: bool = True,
              exclude: Path | None = None) -> list[Path]:
    """Lists the PDFs of the given files and folders, without repeating or entering `exclude`."""
    seen: set[Path] = set()
    found: list[Path] = []
    excluded = exclude.resolve() if exclude else None

    def add(candidate: Path) -> None:
        try:
            key = candidate.resolve()
        except OSError:
            return
        if key in seen or (excluded is not None and (key == excluded or excluded in key.parents)):
            return
        seen.add(key)
        found.append(candidate)

    for raw in paths:
        path = Path(raw)
        if path.is_file() and path.suffix.lower() == ".pdf":
            add(path)
        elif path.is_dir():
            for root, dirs, files in os.walk(path, onerror=lambda _err: None):
                # hidden folders (including the app records one) are left out
                dirs[:] = sorted(name for name in dirs if not name.startswith(".")) \
                    if recursive else []
                for name in sorted(files):
                    if name.lower().endswith(".pdf") and not name.startswith("."):
                        add(Path(root) / name)
    return sorted(found, key=natural_key)


# ---------------------------------------------------------------- one book

def build_entry(path: Path, options: ImportOptions) -> BookEntry:
    """Analyses a PDF and returns the book with the chosen title, author and volume."""
    entry = BookEntry(source=path)
    spec = _spec_or_none(options.filename_pattern)
    parsed, matched = apply_spec(path.stem, spec, options.author_first)
    fixed = spec.fixed if spec is not None else {}
    _apply_file_name(entry, parsed, fixed)
    if not matched:
        entry.note(f"nome fora do padrão '{spec.text}'")
    if not _check_file(entry, path):
        return entry
    info = read_pdf_info(path)
    _apply_pdf_info(entry, info, options, file_name_wins=_file_name_wins(spec, matched, entry))
    if "author" in fixed:
        entry.author, entry.author_origin = fixed["author"], "fixo"
    if parsed.language:
        entry.language = parsed.language
    flag_suspicious_values(entry)
    normalize_authors(entry, options.unknown_author)
    try:
        entry.sha256 = sha256_file(path)
    except OSError as exc:
        entry.fail(f"erro ao calcular o hash ({exc.strerror or exc})")
    return entry


def _spec_or_none(text: str) -> ImportSpec | None:
    try:
        return compile_spec(text)
    except PatternError:  # the interface validates beforehand; here it just must not break
        return None


def _apply_file_name(entry: BookEntry, parsed: ParsedName, fixed: dict[str, str]) -> None:
    entry.title, entry.author, entry.year = parsed.title, parsed.author, parsed.year
    entry.series, entry.series_index = parsed.series, parsed.series_index
    entry.publisher, entry.tags = parsed.publisher, parsed.tags
    if fixed.keys() & {"title", "volume", "series"}:
        entry.title_origin = "fixo"


def _file_name_wins(spec: ImportSpec | None, matched: bool, entry: BookEntry) -> bool:
    return (spec is not None and spec.has_pattern and matched) \
        or entry.series_index is not None or entry.title_origin == "fixo"


def _check_file(entry: BookEntry, path: Path) -> bool:
    """Checks that the file exists, is not empty and is a PDF; otherwise marks an error."""
    try:
        entry.size = path.stat().st_size
    except OSError as exc:
        entry.fail(f"não foi possível ler o arquivo ({exc.strerror or exc})")
        return False
    if entry.size == 0:
        entry.fail("arquivo vazio")
        return False
    if not looks_like_pdf(path):
        entry.fail("não parece ser um PDF válido")
        return False
    return True


def _apply_pdf_info(entry: BookEntry, info: PdfInfo, options: ImportOptions,
                    file_name_wins: bool) -> None:
    entry.pages, entry.language = info.pages, info.language
    if not info.readable:
        entry.fail(f"PDF corrompido ou ilegível ({info.error})", Status.WARNING)
    elif info.locked:
        entry.status = Status.WARNING
        entry.note("PDF protegido por senha: metadados só pelo nome do arquivo")
    elif info.error:
        entry.note(info.error)
    pdf_title = info.title if info.title and not is_junk_title(info.title) else ""
    pdf_author = info.author if info.author and not is_junk_author(info.author) else ""
    if options.prefer_pdf_metadata and not file_name_wins:
        if pdf_title:
            entry.title, entry.title_origin = pdf_title, "pdf"
        if pdf_author:
            entry.author, entry.author_origin = pdf_author, "pdf"
    elif not entry.author and pdf_author:  # the PDF only fills in what is missing
        entry.author, entry.author_origin = pdf_author, "pdf"


def flag_suspicious_values(entry: BookEntry) -> None:
    """'@name - @auth' on 'One Punch Man - Vol 01' puts 'Vol 01' in the author: warns."""
    for label, value in (("autor", entry.author), ("título", entry.title)):
        if looks_like_volume(value):
            entry.note(f"o {label} '{value}' parece um volume: confira o padrão (use @vol)")
    if entry.status is Status.READY and any(n.startswith(_SUSPICIOUS_NOTES)
                                            for n in entry.notes):
        entry.status = Status.WARNING


def normalize_authors(entry: BookEntry, unknown_author: str) -> None:
    """'Assis, Machado de; Outro' -> 'Machado de Assis & Outro' (or unknown author)."""
    names = split_authors(entry.author)
    if names:
        entry.author = " & ".join(names)
        return
    entry.author = unknown_author
    if entry.status is Status.READY:
        entry.status = Status.WARNING
    entry.note("autor não encontrado")


def build_entries(files: list[Path], options: ImportOptions, progress: ProgressFn | None = None,
                  cancel: threading.Event | None = None) -> list[BookEntry]:
    """Analyses the PDFs in parallel, keeping the original order."""
    entries: list[BookEntry] = []
    with ThreadPoolExecutor(max_workers=max(1, options.workers)) as pool:
        futures = [pool.submit(build_entry, path, options) for path in files]
        for index, future in enumerate(futures, start=1):
            if cancel is not None and cancel.is_set():
                for pending in futures:
                    pending.cancel()
                break
            entry = future.result()
            entries.append(entry)
            if progress:
                progress(index, len(files), entry.source.name)
    return entries


# ---------------------------------------------------------------- duplicates

def book_key(title: str, authors: list[str], series: str = "",
             series_index: float | None = None) -> tuple:
    """Identity of a book: title + authors + series + volume (ignoring case and accents).

    Volumes of a collection have the same title and author ("One Punch Man", ONE) and
    only differ by the number, so the volume has to take part in the comparison.
    """
    def norm(text: str) -> str:
        return fold(re.sub(r"[\W_]+", " ", text or "")).strip()

    volume = series_index if series and series_index is not None else None
    return (norm(title), tuple(sorted(norm(a) for a in authors if a.strip())),
            norm(series) if volume is not None else "", volume)


def entry_key(entry: BookEntry) -> tuple:
    return book_key(entry.title, entry.authors or [entry.author], entry.series,
                    entry.series_index)


def mark_duplicates(entries: list[BookEntry], options: ImportOptions) -> int:
    """Marks identical copies and warns about the same book in different files.
    Returns how many files were marked as duplicates."""
    duplicates = mark_identical_files(entries, options)
    warn_same_book(entries)
    return duplicates


def mark_identical_files(entries: list[BookEntry], options: ImportOptions) -> int:
    """Copies with the same content: the one with the best metadata stays, the others are marked."""
    def quality(entry: BookEntry) -> tuple[bool, bool, bool]:
        return (entry.author != options.unknown_author, entry.author_origin == "pdf",
                entry.title_origin == "pdf")

    groups: dict[str, list[BookEntry]] = {}
    for entry in entries:
        if entry.status in USABLE_STATUSES and entry.sha256:
            groups.setdefault(entry.sha256, []).append(entry)
    duplicates = 0
    for group in groups.values():
        best = max(group, key=quality)
        for entry in (item for item in group if item is not best):
            duplicates += 1
            if options.skip_duplicates:
                entry.fail(f"idêntico a {best.source.name}", Status.DUPLICATE)
            else:
                entry.note(f"idêntico a {best.source.name}")
    return duplicates


def warn_same_book(entries: list[BookEntry]) -> None:
    """Same title, author and volume in different files: warns (it may be the same book)."""
    first_by_key: dict[tuple, BookEntry] = {}
    for entry in entries:
        if entry.status not in USABLE_STATUSES or any(n.startswith("idêntico a")
                                                      for n in entry.notes):
            continue
        other = first_by_key.setdefault(entry_key(entry), entry)
        if other is not entry:
            entry.status = Status.WARNING
            entry.note(f"mesmo título, autor e volume de {other.source.name} (arquivo diferente)")


def summarize(entries: Iterable[BookEntry]) -> Counter:
    """Counts the books by state."""
    return Counter(entry.status for entry in entries)
