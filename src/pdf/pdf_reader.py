"""Reading PDFs: title, author, language and pages from inside the file."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from ..core.text import normalize_text

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
    """What could be read from inside the PDF."""

    title: str = ""
    author: str = ""
    language: str | None = None
    pages: int = 0
    encrypted: bool = False
    locked: bool = False  # needs a password
    readable: bool = True
    error: str = ""


def is_junk_title(title: str) -> bool:
    """Automatic titles left by programs ('Microsoft Word - doc1', 'untitled')."""
    title = normalize_text(title)
    if len(title) < 2 or _JUNK_TITLE_EXACT.match(title):
        return True
    return any(pattern.search(title) for pattern in _JUNK_TITLE_PATTERNS)


def is_junk_author(author: str) -> bool:
    """Automatic authors ('admin', 'Acrobat PDFMaker', e-mails)."""
    author = normalize_text(author)
    if len(author) < 2 or author.lower() in _JUNK_AUTHORS:
        return True
    return bool(_JUNK_AUTHOR_PATTERN.search(author))


def looks_like_pdf(path: Path) -> bool:
    """Checks for the '%PDF-' signature at the start of the file."""
    try:
        with path.open("rb") as handle:
            return b"%PDF-" in handle.read(1024)
    except OSError:
        return False


def _language_code(value: object) -> str | None:
    match = _LANG_CODE.match(str(value or "").strip())
    return match.group(1).lower() if match else None


def read_pdf_info(path: Path) -> PdfInfo:
    """Reads title, author, language and page count; never raises."""
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
        except Exception:  # catalog without /Lang or malformed: not critical
            info.language = None
    except Exception as exc:  # pypdf raises several types for bad files
        logger.warning("Failed to read %s: %s", path, exc)
        info.readable = False
        info.error = f"{type(exc).__name__}: {exc}"
    return info


def first_pages_text(path: Path, pages: int = 3, max_chars: int = 2500) -> str:
    """Text of the first pages (cover, title page, copyright page).

    Limited so that the query sent to the AI stays small. Scanned PDFs (image only) or
    protected ones return "" and the AI works from the file name and metadata alone.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return ""
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:pages])
    except Exception as exc:  # bad file: the AI works without the text
        logger.info("No text from %s: %s", path, exc)
        return ""
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
    return text[:max_chars]
