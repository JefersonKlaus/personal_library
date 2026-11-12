"""Análise dos PDFs escolhidos: achar os arquivos, montar cada livro e marcar duplicados.

Regras de prioridade dos metadados de um livro:
1. valores fixos de "Como importar" (@auth=ONE) vencem tudo;
2. o nome do arquivo vence quando segue o padrão do usuário ou traz o volume
   (o título de dentro do PDF, "One Punch Man", perderia o "Vol 18");
3. senão, com "Preferir metadados de dentro do PDF", vale o que está no PDF;
4. o PDF sempre completa o que faltou (por exemplo, o autor).
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
from ..parsing.filename_parser import ParsedName
from ..parsing.import_spec import ImportSpec, PatternError, apply_spec, compile_spec
from ..core.models import USABLE_STATUSES, BookEntry, ImportOptions, Status
from ..pdf.pdf_reader import PdfInfo, is_junk_author, is_junk_title, looks_like_pdf, read_pdf_info
from ..parsing.people import split_authors
from ..core.text import fold, natural_key
from ..parsing.volumes import looks_like_volume

ProgressFn = Callable[[int, int, str], None]
_SUSPICIOUS_NOTES = ("nome fora do padrão", "o autor", "o título")
# Observações que deixam o livro com "atenção" (e que o usuário deve conferir).
WARNING_NOTES = _SUSPICIOUS_NOTES + ("autor não encontrado", "PDF protegido", "mesmo título")


# ---------------------------------------------------------------- arquivos

def find_pdfs(paths: Iterable[Path | str], recursive: bool = True,
              exclude: Path | None = None) -> list[Path]:
    """Lista os PDFs de arquivos e pastas dados, sem repetir nem entrar em `exclude`."""
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
                # pastas ocultas (inclui a de registros do app) ficam de fora
                dirs[:] = sorted(name for name in dirs if not name.startswith(".")) \
                    if recursive else []
                for name in sorted(files):
                    if name.lower().endswith(".pdf") and not name.startswith("."):
                        add(Path(root) / name)
    return sorted(found, key=natural_key)


# ---------------------------------------------------------------- um livro

def build_entry(path: Path, options: ImportOptions) -> BookEntry:
    """Analisa um PDF e devolve o livro com título, autor e volume escolhidos."""
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
    except PatternError:  # a interface valida antes; aqui só não pode quebrar
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
    """Confere se o arquivo existe, não está vazio e é PDF; senão marca erro."""
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
    elif not entry.author and pdf_author:  # o PDF só completa o que faltou
        entry.author, entry.author_origin = pdf_author, "pdf"


def flag_suspicious_values(entry: BookEntry) -> None:
    """'@name - @auth' em 'One Punch Man - Vol 01' põe 'Vol 01' no autor: avisa."""
    for label, value in (("autor", entry.author), ("título", entry.title)):
        if looks_like_volume(value):
            entry.note(f"o {label} '{value}' parece um volume: confira o padrão (use @vol)")
    if entry.status is Status.READY and any(n.startswith(_SUSPICIOUS_NOTES)
                                            for n in entry.notes):
        entry.status = Status.WARNING


def normalize_authors(entry: BookEntry, unknown_author: str) -> None:
    """'Assis, Machado de; Outro' -> 'Machado de Assis & Outro' (ou autor desconhecido)."""
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
    """Analisa os PDFs em paralelo, mantendo a ordem original."""
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


# ---------------------------------------------------------------- duplicados

def book_key(title: str, authors: list[str], series: str = "",
             series_index: float | None = None) -> tuple:
    """Identidade de um livro: título + autores + série + volume (sem caixa e acentos).

    Volumes de uma coleção têm o mesmo título e autor ("One Punch Man", ONE) e só se
    diferenciam pelo número, então o volume precisa entrar na comparação.
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
    """Marca cópias idênticas e avisa sobre o mesmo livro em arquivos diferentes.
    Devolve quantos arquivos foram marcados como duplicados."""
    duplicates = mark_identical_files(entries, options)
    warn_same_book(entries)
    return duplicates


def mark_identical_files(entries: list[BookEntry], options: ImportOptions) -> int:
    """Cópias com o mesmo conteúdo: fica a de melhor metadado, as outras são marcadas."""
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
    """Mesmo título, autor e volume em arquivos diferentes: avisa (pode ser o mesmo livro)."""
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
    """Conta os livros por situação."""
    return Counter(entry.status for entry in entries)
