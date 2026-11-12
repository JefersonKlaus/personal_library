"""Leitura de PDFs: título, autor, idioma e páginas de dentro do arquivo."""
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


def first_pages_text(path: Path, pages: int = 3, max_chars: int = 2500) -> str:
    """Texto das primeiras páginas (capa, folha de rosto, ficha catalográfica).

    Limitado para a consulta à IA ficar pequena. PDFs escaneados (só imagem) ou
    protegidos devolvem "" e a IA usa só o nome do arquivo e os metadados.
    """
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            return ""
        text = "\n".join((page.extract_text() or "") for page in reader.pages[:pages])
    except Exception as exc:  # arquivo ruim: a IA trabalha sem o texto
        logger.info("Sem texto de %s: %s", path, exc)
        return ""
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", text)).strip()
    return text[:max_chars]
