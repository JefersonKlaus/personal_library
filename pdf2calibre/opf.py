"""Geração do OPF que o Calibre lê ao adicionar o livro.

Regras do Calibre (conferidas no código dele, calibre/ebooks/metadata/meta.py):

* O OPF só é usado se tiver um `<dc:identifier opf:scheme="calibre">`.
  Sem ele o Calibre ignora o arquivo e usa os metadados de dentro do PDF
  (muitas vezes "Microsoft Word - doc1" / "admin").
* Ao adicionar um arquivo solto (Adicionar livros, arrastar, pasta de adição
  automática, `calibredb add arquivo.pdf`), o Calibre só procura um OPF com o
  mesmo nome do livro: `Título - Autor.pdf` -> `Título - Autor.opf`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
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


@dataclass
class OpfData:
    """Os metadados que vão para o OPF (vindos de um PDF importado ou da biblioteca)."""

    title: str
    authors: list[str]
    uid_seed: str  # gera o uuid estável do OPF
    author_sort: str = ""  # do livro todo: 'Lima, Ana & Dias, Rui'; vazio = calcula
    title_sort: str = ""
    pubdate: str = ""  # ISO 8601
    languages: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    series: str = ""
    series_index: float = 1.0
    publisher: str = ""
    identifiers: dict[str, str] = field(default_factory=dict)  # {'isbn': '978...'}
    comments: str = ""  # HTML, como o Calibre guarda


def render_opf(data: OpfData, cover_name: str | None = None) -> str:
    """Monta o texto do arquivo OPF 2.0."""
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, data.uid_seed)
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">',
        # Marca exigida pelo Calibre para confiar no OPF; o valor não é usado ao
        # adicionar (o Calibre cria um id e um uuid novos para o livro).
        f'    <dc:identifier opf:scheme="calibre" id="calibre_id">{identifier}</dc:identifier>',
        f'    <dc:identifier opf:scheme="uuid" id="uuid_id">{identifier}</dc:identifier>',
        f"    <dc:title>{escape(data.title)}</dc:title>",
    ]
    # Convenção do Calibre: todo criador leva o author_sort do livro inteiro, e ele
    # lê o do primeiro. Um valor por autor perderia os coautores na ordenação.
    file_as = data.author_sort or " & ".join(author_sort(name) for name in data.authors)
    for name in data.authors:
        lines.append(
            f"    <dc:creator opf:file-as={quoteattr(file_as)} "
            f'opf:role="aut">{escape(name)}</dc:creator>'
        )
    if data.pubdate:
        lines.append(f"    <dc:date>{escape(data.pubdate)}</dc:date>")
    if data.publisher:
        lines.append(f"    <dc:publisher>{escape(data.publisher)}</dc:publisher>")
    for kind, value in sorted(data.identifiers.items()):
        if kind.lower() not in ("calibre", "uuid") and value:
            lines.append(f"    <dc:identifier opf:scheme={quoteattr(kind.upper())}>"
                         f"{escape(value)}</dc:identifier>")
    for code in data.languages:  # idioma desconhecido: melhor omitir do que afirmar "und"
        language = language_code(code)
        if language:
            lines.append(f"    <dc:language>{escape(language)}</dc:language>")
    for tag in data.tags:
        if tag.strip():
            lines.append(f"    <dc:subject>{escape(tag.strip())}</dc:subject>")
    if data.comments:
        lines.append(f"    <dc:description>{escape(data.comments)}</dc:description>")
    if data.series:
        lines.append(f"    <meta name=\"calibre:series\" content={quoteattr(data.series)}/>")
        lines.append(f"    <meta name=\"calibre:series_index\" "
                     f"content=\"{data.series_index:g}\"/>")
    lines.append(
        f"    <meta name=\"calibre:title_sort\" "
        f"content={quoteattr(data.title_sort or title_sort(data.title))}/>"
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


def entry_opf_data(entry: BookEntry, tags: Iterable[str] = ()) -> OpfData:
    """Metadados de um PDF importado (revisado na aba Importar)."""
    # Meio-dia UTC: o Calibre mostra a data no fuso local, e meia-noite UTC
    # viraria "dez. do ano anterior" no Brasil (UTC-3).
    pubdate = f"{entry.year:04d}-01-01T12:00:00+00:00" if entry.year else ""
    return OpfData(
        title=entry.title, authors=entry.authors or [entry.author],
        uid_seed=entry.sha256 or str(entry.source), pubdate=pubdate,
        languages=[entry.language] if entry.language else [],
        tags=list(dict.fromkeys([*tags, *entry.tags])), publisher=entry.publisher,
        series=entry.series,
        series_index=entry.series_index if entry.series_index is not None else 1.0)


def build_opf(entry: BookEntry, tags: Iterable[str] = (), cover_name: str | None = None) -> str:
    """OPF de um PDF importado."""
    return render_opf(entry_opf_data(entry, tags), cover_name)


def write_opf(path: Path, entry: BookEntry, tags: Iterable[str] = (),
              cover_name: str | None = None) -> Path:
    """Grava o OPF de um PDF importado (UTF-8) e devolve o caminho."""
    path.write_text(build_opf(entry, tags, cover_name), encoding="utf-8")
    return path
