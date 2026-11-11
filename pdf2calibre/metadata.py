"""Leitura de metadados de PDFs (pypdf) e montagem de um BookEntry."""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .models import BookEntry, Options, Status
from .naming import (PatternError, apply_spec, compile_spec, looks_like_volume,
                     normalize_text, split_authors)

logger = logging.getLogger(__name__)

_JUNK_TITLE_EXACT = re.compile(
    r"^(untitled|sem t[ií]tulo|document\d*|documento\d*|doc\d*|scan\w*|pdf|"
    r"unknown|null|none|new document|slide\d*|capa|cover)$",
    re.I,
)
_JUNK_TITLE_PATTERNS = [
    re.compile(r"^microsoft\s+(word|powerpoint|excel)\s*-", re.I),
    re.compile(r"\.(docx?|indd|qxd|pub|pptx?|tex|odt|rtf|xlsx?|psd|ai|pdf|txt|html?)$", re.I),
    re.compile(r"^[\W\d_]+$"),
]
_JUNK_AUTHORS = {
    "admin", "administrator", "administrador", "user", "usuario", "usuário",
    "owner", "unknown", "desconhecido", "author", "autor", "pc", "acrobat",
    "adobe", "scanner", "scan", "microsoft", "windows user", "default",
    "null", "none", "anonymous", "anônimo", "anonimo",
}
_JUNK_AUTHOR_PATTERN = re.compile(r"(@|\.com\b|pdf|acrobat|distiller|converter|office)", re.I)

_LANG_CODE = re.compile(r"^([A-Za-z]{2,3})(?:[-_]|$)")


@dataclass
class PdfInfo:
    """O que foi possível ler de dentro do PDF."""

    title: str = ""
    author: str = ""
    language: str | None = None
    pages: int = 0
    encrypted: bool = False
    locked: bool = False  # exige senha
    readable: bool = True
    error: str = ""


def is_junk_title(title: str) -> bool:
    """Títulos automáticos de programas ('Microsoft Word - doc1', 'untitled')."""
    title = normalize_text(title)
    if len(title) < 2 or _JUNK_TITLE_EXACT.match(title):
        return True
    return any(pattern.search(title) for pattern in _JUNK_TITLE_PATTERNS)


def is_junk_author(author: str) -> bool:
    """Autores automáticos ('admin', 'Acrobat PDFMaker', e-mails)."""
    author = normalize_text(author)
    if len(author) < 2 or author.lower() in _JUNK_AUTHORS:
        return True
    return bool(_JUNK_AUTHOR_PATTERN.search(author))


def looks_like_pdf(path: Path) -> bool:
    """Confere se há a assinatura '%PDF-' no início do arquivo."""
    try:
        with path.open("rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
        return False


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """Hash SHA-256 do arquivo, lido em blocos."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


def _language_code(value: object) -> str | None:
    match = _LANG_CODE.match(str(value or "").strip())
    return match.group(1).lower() if match else None


def read_pdf_info(path: Path) -> PdfInfo:
    """Lê título, autor, idioma e número de páginas; nunca levanta exceção."""
    info = PdfInfo()
    try:
        from pypdf import PdfReader
    except ImportError:
        info.error = "pypdf não está instalado; usando só o nome do arquivo"
        return info

    try:
        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted:
            info.encrypted = True
            if not reader.decrypt(""):
                info.locked = True
                return info
        info.pages = len(reader.pages)
        meta = reader.metadata
        if meta is not None:
            info.title = normalize_text(str(meta.title or ""))
            info.author = normalize_text(str(meta.author or ""))
        try:
            info.language = _language_code(reader.trailer["/Root"].get("/Lang"))
        except Exception:  # catálogo sem /Lang ou malformado: não é crítico
            info.language = None
    except Exception as exc:  # pypdf levanta vários tipos para arquivos ruins
        logger.warning("Falha ao ler %s: %s", path, exc)
        info.readable = False
        info.error = f"{type(exc).__name__}: {exc}"
    return info


def build_entry(path: Path, options: Options) -> BookEntry:
    """Analisa um PDF e devolve o BookEntry com título e autor escolhidos."""
    entry = BookEntry(source=path)
    try:
        spec = compile_spec(options.filename_pattern)
    except PatternError:  # a interface valida antes; aqui só não pode quebrar
        spec = None
    parsed, matched = apply_spec(path.stem, spec, options.author_first)
    if not matched:
        entry.note(f"nome fora do padrão '{spec.text}'")
    fixed = spec.fixed if spec is not None else {}
    entry.title, entry.author, entry.year = parsed.title, parsed.author, parsed.year
    entry.series, entry.series_index = parsed.series, parsed.series_index
    entry.publisher, entry.tags = parsed.publisher, parsed.tags
    if fixed.keys() & {"title", "volume", "series"}:
        entry.title_origin = "fixo"
    # O nome do arquivo manda quando segue o padrão do usuário, traz o volume ou tem
    # valor fixo: o título de dentro do PDF ("One Punch Man") perderia o "Vol 18".
    filename_wins = (spec is not None and spec.has_pattern and matched) \
        or parsed.series_index is not None or entry.title_origin == "fixo"

    try:
        entry.size = path.stat().st_size
    except OSError as exc:
        entry.fail(f"não foi possível ler o arquivo ({exc.strerror or exc})")
        return entry
    if entry.size == 0:
        entry.fail("arquivo vazio")
        return entry
    if not looks_like_pdf(path):
        entry.fail("não parece ser um PDF válido")
        return entry

    info = read_pdf_info(path)
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
    if options.prefer_pdf_metadata and not filename_wins:
        if pdf_title:
            entry.title, entry.title_origin = pdf_title, "pdf"
        if pdf_author:
            entry.author, entry.author_origin = pdf_author, "pdf"
    elif not entry.author and pdf_author:  # o PDF só completa o que faltou
        entry.author, entry.author_origin = pdf_author, "pdf"
    # Valores fixos ("@auth=ONE") valem para todos os arquivos e vencem tudo.
    if "author" in fixed:
        entry.author, entry.author_origin = fixed["author"], "fixo"
    if parsed.language:
        entry.language = parsed.language
    # "@name - @auth" em "One Punch Man - Vol 01" põe "Vol 01" no autor: avisa.
    for label, value in (("autor", entry.author), ("título", entry.title)):
        if looks_like_volume(value):
            entry.note(f"o {label} '{value}' parece um volume: confira o padrão (use @vol)")
    if any(note.startswith(("nome fora do padrão", "o autor", "o título"))
           for note in entry.notes) and entry.status is Status.READY:
        entry.status = Status.WARNING

    names = split_authors(entry.author)
    if names:
        entry.author = " & ".join(names)
    else:
        entry.author = options.unknown_author
        if entry.status is Status.READY:
            entry.status = Status.WARNING
        entry.note("autor não encontrado")

    try:
        entry.sha256 = sha256_file(path)
    except OSError as exc:
        entry.fail(f"erro ao calcular o hash ({exc.strerror or exc})")
    return entry
