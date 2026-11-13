"""OPF file: the metadata that travels with the book (title, authors, series...).

Rules of the library (checked in the code of the external program):
* the OPF is only used if it has the OPF_TRUSTED_SCHEME identifier; without it the
  library ignores the file and uses the metadata from inside the PDF;
* when a loose file is added, only the OPF with the same name as the book is read
  (`Título - Autor.pdf` -> `Título - Autor.opf`);
* every author carries the sort name of the whole book ('Lima, Ana & Dias, Rui'), and
  the library reads the one of the first author.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from xml.sax.saxutils import escape, quoteattr

from ..core.text import title_sort
from ..parsing.people import author_sort
from .manager import OPF_META_PREFIX, OPF_TRUSTED_SCHEME

# Most common 2-letter codes converted to the 3-letter ones the library uses.
_LANGUAGES = {
    "pt": "por", "en": "eng", "es": "spa", "fr": "fra",
    "de": "deu", "it": "ita", "nl": "nld", "ru": "rus",
}


def language_code(code: str | None) -> str | None:
    """Converts 'pt' into 'por'; unknown codes pass through unchanged."""
    if not code:
        return None
    return _LANGUAGES.get(code.lower(), code.lower())


@dataclass
class OpfData:
    """The metadata that goes into the OPF."""

    title: str
    authors: list[str]
    uid_seed: str  # builds the stable uuid of the OPF
    author_sort: str = ""  # of the whole book: 'Lima, Ana & Dias, Rui'; empty = computed
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
    """Builds the text of the OPF 2.0 file."""
    identifier = uuid.uuid5(uuid.NAMESPACE_URL, data.uid_seed)
    meta = OPF_META_PREFIX
    file_as = data.author_sort or " & ".join(author_sort(name) for name in data.authors)
    lines = [
        "<?xml version='1.0' encoding='utf-8'?>",
        '<package xmlns="http://www.idpf.org/2007/opf" unique-identifier="uuid_id" version="2.0">',
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:opf="http://www.idpf.org/2007/opf">',
        # The value does not matter: the library creates a new id and uuid when adding.
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
    for code in data.languages:  # unknown language: better to omit it than to claim "und"
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
