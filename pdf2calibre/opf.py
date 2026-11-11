"""Geração do metadata.opf que o Calibre lê ao adicionar uma pasta de livro."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Iterable
from xml.sax.saxutils import escape, quoteattr

from .models import BookEntry
from .naming import author_sort, title_sort

# O Calibre aceita códigos de 2 ou 3 letras; os mais comuns vão em 3.
_LANGUAGES = {
    "pt": "por", "en": "eng", "es": "spa", "fr": "fra",
    "de": "deu", "it": "ita", "nl": "nld", "ru": "rus",
}


def language_code(code: str | None) -> str | None:
    """Converte 'pt' em 'por'; códigos desconhecidos passam sem mudar."""
    if not code:
        return None
    return _LANGUAGES.get(code.lower(), code.lower())


def build_opf(entry: BookEntry, tags: Iterable[str] = (), cover_name: str | None = None) -> str:
    """Monta o texto do arquivo OPF 2.0 para o livro."""
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, entry.sha256 or str(entry.source))
    authors = entry.authors or [entry.author]
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">',
        f'    <dc:identifier opf:scheme="uuid" id="uuid_id">{identifier}</dc:identifier>',
        f"    <dc:title>{escape(entry.title)}</dc:title>",
    ]
    for name in authors:
        lines.append(
            f"    <dc:creator opf:file-as={quoteattr(author_sort(name))} "
            f'opf:role="aut">{escape(name)}</dc:creator>'
        )
    language = language_code(entry.language)
    if language:  # idioma desconhecido: melhor omitir do que afirmar "und"
        lines.append(f"    <dc:language>{escape(language)}</dc:language>")
    if entry.year:
        lines.append(f"    <dc:date>{entry.year:04d}-01-01T00:00:00+00:00</dc:date>")
    for tag in tags:
        if tag.strip():
            lines.append(f"    <dc:subject>{escape(tag.strip())}</dc:subject>")
    lines.append(
        f"    <meta name=\"calibre:title_sort\" content={quoteattr(title_sort(entry.title))}/>"
    )
    lines.append("  </metadata>")
    if cover_name:
        lines.append("  <guide>")
        lines.append(
            f'    <reference type="cover" title="Cover" href={quoteattr(cover_name)}/>'
        )
        lines.append("  </guide>")
    lines.append("</package>")
    return "\n".join(lines) + "\n"


def write_opf(path: Path, entry: BookEntry, tags: Iterable[str] = (),
              cover_name: str | None = None) -> Path:
    """Grava o OPF em disco (UTF-8) e devolve o caminho."""
    path.write_text(build_opf(entry, tags, cover_name), encoding="utf-8")
    return path
