"""Editing the metadata of books (through the library tool): one book, or many at once.

The dialog works with text (what the user sees and types); this module turns that text
into the values the library tool expects (`calibredb set_metadata --field name:value`),
validates it, and writes only what really changed in each book:

* title -> title + sort (the sort name would otherwise keep the old title);
* authors 'A & B' -> authors + author_sort ('Lima, Ana & Dias, Rui');
* year -> pubdate at noon UTC (midnight would show the previous year in Brazil);
* tags and languages separated by commas, identifiers as 'isbn:978...,doi:10...';
* the description is edited as plain text and saved as simple HTML paragraphs.
"""
from __future__ import annotations

import html
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..core.text import html_to_text, normalize_text, title_sort
from ..parsing.people import author_sort
from .cli import LibraryCli
from .database import LibraryBook
from .opf import language_code

ProgressFn = Callable[[int, int, str], None]
Fields = dict[str, str]  # `--field` name -> value, for the library tool

UNKNOWN_AUTHOR = "Unknown"  # what the library uses for a book without authors
UNDEFINED_DATE = "0101-01-01T00:00:00+00:00"  # how the library stores "no date"
_LANGUAGE = re.compile(r"^[a-z]{2,3}$")
_YEAR = re.compile(r"^\d{1,4}$")


class MetadataError(ValueError):
    """Invalid value (message ready to be shown)."""


# ---------------------------------------------------------------- text -> library fields
# One function per field of the dialog: the text the user typed -> the `--field` values.

def _split(text: str, separator: str) -> list[str]:
    """Splits, cleans and drops empty and repeated items (ignoring case)."""
    items: dict[str, str] = {}
    for part in text.split(separator):
        part = normalize_text(part)
        if part and part.casefold() not in items:
            items[part.casefold()] = part
    return list(items.values())


def _title(text: str) -> Fields:
    title = normalize_text(text)
    if not title:
        raise MetadataError("O título não pode ficar vazio.")
    return {"title": title, "sort": title_sort(title)}


def _authors(text: str) -> Fields:
    authors = _split(text, "&") or [UNKNOWN_AUTHOR]
    return {"authors": " & ".join(authors),
            "author_sort": " & ".join(author_sort(name) for name in authors)}


def _volume(text: str) -> Fields:
    try:
        number = float(text.strip().replace(",", ".") or "1")
    except ValueError:
        number = -1.0
    if not 0 <= number < 100000:
        raise MetadataError(f"Volume inválido: '{text.strip()}'. Use um número (ex.: 3 ou 2.5).")
    return {"series_index": f"{number:g}"}


def _year(text: str) -> Fields:
    year = text.strip()
    if not year:
        return {"pubdate": UNDEFINED_DATE}
    if not _YEAR.match(year) or not 1000 <= int(year) <= 9999:
        raise MetadataError(f"Ano inválido: '{year}'. Use 4 dígitos (ex.: 1999).")
    # Noon UTC: the date is shown in the local time zone, and midnight UTC would
    # become December of the previous year in Brazil (UTC-3).
    return {"pubdate": f"{int(year):04d}-01-01T12:00:00+00:00"}


def _languages(text: str) -> Fields:
    codes: list[str] = []
    for item in _split(text, ","):
        code = language_code(item) or ""
        if not _LANGUAGE.match(code):
            raise MetadataError(f"Idioma inválido: '{item}'. Use códigos como pt, en ou por.")
        if code not in codes:
            codes.append(code)
    return {"languages": ",".join(codes)}


def _identifiers(text: str) -> Fields:
    pairs: dict[str, str] = {}
    for item in filter(str.strip, text.split(",")):
        kind, _sep, value = item.partition(":")
        kind, value = kind.strip().lower(), value.strip()
        if not kind or not value:
            raise MetadataError(f"Identificador inválido: '{item.strip()}'. "
                                "Use tipo:valor (ex.: isbn:9788535910667).")
        pairs[kind] = value
    return {"identifiers": ",".join(f"{kind}:{value}" for kind, value in sorted(pairs.items()))}


def _comments(text: str) -> Fields:
    """Plain text -> '<p>...</p>' paragraphs (blank lines separate them)."""
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text.strip())]
    return {"comments": "".join("<p>" + html.escape(part).replace("\n", "<br>") + "</p>"
                                for part in paragraphs if part)}


@dataclass(frozen=True)
class Field:
    """A field of the dialog: how a book shows it, and what typing in it writes."""

    show: Callable[[LibraryBook], str]
    write: Callable[[str], Fields]


# In the order of the dialog (and series before series_index, as the library expects).
FIELDS: dict[str, Field] = {
    "title": Field(lambda book: book.title, _title),
    "authors": Field(lambda book: " & ".join(book.authors), _authors),
    "series": Field(lambda book: book.series,
                    lambda text: {"series": normalize_text(text)}),
    "series_index": Field(lambda book: f"{book.series_index:g}", _volume),
    "year": Field(lambda book: str(book.year) if book.year else "", _year),
    "publisher": Field(lambda book: book.publisher,
                       lambda text: {"publisher": normalize_text(text)}),
    "tags": Field(lambda book: ", ".join(book.tags),
                  lambda text: {"tags": ",".join(sorted(_split(text, ","), key=str.casefold))}),
    "languages": Field(lambda book: ", ".join(book.languages), _languages),
    "identifiers": Field(lambda book: ", ".join(f"{kind}:{value}" for kind, value
                                                in sorted(book.identifiers.items())),
                         _identifiers),
    "comments": Field(lambda book: html_to_text(book.comments), _comments),
}
# The same value in many books makes no sense for these (every book would get the same
# volume number or ISBN), so they are only edited one book at a time.
SINGLE_BOOK_ONLY = {"series_index": "Volume", "identifiers": "Identificadores"}


def current_text(book: LibraryBook, key: str) -> str:
    """The value of a field as the dialog shows it (and as the user would type it)."""
    return FIELDS[key].show(book)


def common_text(books: list[LibraryBook], key: str) -> str | None:
    """The value shared by every book, or None when they differ (several books)."""
    values = {current_text(book, key) for book in books}
    return values.pop() if len(values) == 1 else None


def library_fields(key: str, text: str) -> Fields:
    """The `--field` values for one field of the dialog. Raises MetadataError."""
    return FIELDS[key].write(text or "")


def validate(values: dict[str, str], book_count: int) -> None:
    """Checks every value before anything is written. Raises MetadataError."""
    if not values:
        raise MetadataError("Marque pelo menos um campo para gravar.")
    if book_count > 1:
        single = [name for key, name in SINGLE_BOOK_ONLY.items() if key in values]
        if single:
            raise MetadataError(f"{' e '.join(single)}: só dá para editar um livro por vez.")
    for key, text in values.items():
        library_fields(key, text)


def changes_for(book: LibraryBook, values: dict[str, str]) -> dict[str, str]:
    """The `--field` values that really change this book (empty = nothing to do).

    Old and new go through the same conversion, so typing the same thing differently
    ('a,b' for 'a, b') is not a change, and untouched fields keep what the library has
    (an HTML description, an author sort name adjusted in the library program)."""
    fields: dict[str, str] = {}
    for key in FIELDS:  # series before series_index, like the library expects
        if key not in values:
            continue
        new = library_fields(key, values[key])
        try:
            old = library_fields(key, current_text(book, key))
        except MetadataError:  # odd value in the library (e.g. empty title): rewrite it
            old = {}
        if new != old:
            fields.update(new)
    return fields


# ---------------------------------------------------------------- writing

@dataclass
class EditReport:
    total: int = 0
    done: int = 0  # changed
    unchanged: int = 0  # already had those values
    failed: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)

    def summary(self) -> str:
        text = f"Metadados gravados em {self.done} de {self.total} livro(s)"
        if self.unchanged:
            text += f"; {self.unchanged} já estavam assim"
        if self.failed:
            text += f"; {self.failed} com erro"
        return text + (" (cancelado)." if self.cancelled else ".")


def apply_changes(cli: LibraryCli, library: Path, books: list[LibraryBook],
                  values: dict[str, str], progress: ProgressFn | None = None,
                  cancel: threading.Event | None = None) -> EditReport:
    """Writes the values in every book (one book at a time). Raises MetadataError
    before writing anything if a value is invalid."""
    validate(values, len(books))
    report = EditReport(total=len(books))
    for index, book in enumerate(books, start=1):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        fields = changes_for(book, values)
        if not fields:
            report.unchanged += 1
        else:
            ok, error = cli.set_fields(library, book.id, fields)
            if ok:
                report.done += 1
            else:
                report.failed += 1
                report.errors.append(f"{book.title}: {error}")
        if progress:
            progress(index, report.total, book.title)
    return report
