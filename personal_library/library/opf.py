"""Arquivo OPF: os metadados que acompanham o livro (título, autores, série...).

Regras da biblioteca (conferidas no código do programa externo):
* o OPF só é usado se tiver o identificador OPF_TRUSTED_SCHEME; sem ele a
  biblioteca ignora o arquivo e usa os metadados de dentro do PDF;
* ao adicionar um arquivo solto, só é lido o OPF com o mesmo nome do livro
  (`Título - Autor.pdf` -> `Título - Autor.opf`);
* todo autor leva a ordenação do livro inteiro ('Lima, Ana & Dias, Rui'), e a
  biblioteca lê a do primeiro.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from ..people import author_sort
from ..text import title_sort
from .manager import OPF_META_PREFIX, OPF_TRUSTED_SCHEME

# Códigos de 2 letras mais comuns convertidos para os de 3 que a biblioteca usa.
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
    """Os metadados que vão para o OPF."""

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
    comments: str = ""  # HTML


def render_opf(data: OpfData, cover_name: str | None = None) -> str:
    """Monta o texto do arquivo OPF 2.0."""
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, data.uid_seed)
    meta = OPF_META_PREFIX
    file_as = data.author_sort or " & ".join(author_sort(name) for name in data.authors)
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">',
        # O valor não importa: a biblioteca cria id e uuid novos ao adicionar.
        f'    <dc:identifier opf:scheme="{OPF_TRUSTED_SCHEME}" id="app_id">{identifier}'
        "</dc:identifier>",
        f'    <dc:identifier opf:scheme="uuid" id="uuid_id">{identifier}</dc:identifier>',
        f"    <dc:title>{escape(data.title)}</dc:title>",
    ]
    lines += [f"    <dc:creator opf:file-as={quoteattr(file_as)} opf:role=\"aut\">"
              f"{escape(name)}</dc:creator>" for name in data.authors]
    if data.pubdate:
        lines.append(f"    <dc:date>{escape(data.pubdate)}</dc:date>")
    if data.publisher:
        lines.append(f"    <dc:publisher>{escape(data.publisher)}</dc:publisher>")
    for kind, value in sorted(data.identifiers.items()):
        if kind.lower() not in (OPF_TRUSTED_SCHEME, "uuid") and value:
            lines.append(f"    <dc:identifier opf:scheme={quoteattr(kind.upper())}>"
                         f"{escape(value)}</dc:identifier>")
    for code in data.languages:  # idioma desconhecido: melhor omitir do que afirmar "und"
        if language_code(code):
            lines.append(f"    <dc:language>{escape(language_code(code))}</dc:language>")
    lines += [f"    <dc:subject>{escape(tag.strip())}</dc:subject>"
              for tag in data.tags if tag.strip()]
    if data.comments:
        lines.append(f"    <dc:description>{escape(data.comments)}</dc:description>")
    if data.series:
        lines.append(f"    <meta name=\"{meta}series\" content={quoteattr(data.series)}/>")
        lines.append(f"    <meta name=\"{meta}series_index\" content=\"{data.series_index:g}\"/>")
    lines.append(f"    <meta name=\"{meta}title_sort\" "
                 f"content={quoteattr(data.title_sort or title_sort(data.title))}/>")
    lines.append("  </metadata>")
    if cover_name:
        lines += ["  <guide>",
                  f'    <reference type="cover" title="Cover" href={quoteattr(cover_name)}/>',
                  "  </guide>"]
    lines.append("</package>")
    return "\n".join(lines) + "\n"
