"""Preencher título, autor, série, volume... com IA (Groq), um PDF por vez.

A IA recebe pistas de cada livro (nome do arquivo, metadados do PDF, o que o app
já deduziu e o texto das primeiras páginas) e responde um JSON com os dados.
Regras: valores fixos de "Como importar" (@auth=ONE) continuam valendo; o que a IA
não souber (null) mantém o que o app já tinha deduzido.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Callable

from .analysis import WARNING_NOTES, flag_suspicious_values, normalize_authors
from .groq_client import GroqClient, GroqError
from ..core.models import USABLE_STATUSES, BookEntry, Status
from ..pdf.pdf_reader import first_pages_text, is_junk_author, is_junk_title, read_pdf_info

logger = logging.getLogger(__name__)
ProgressFn = Callable[[int, int, str], None]
LOW_CONFIDENCE = 0.5
LOW_CONFIDENCE_NOTE = "IA pouco confiante: confira os dados"
NO_ANSWER_NOTE = "IA não respondeu"
# Observações que deixam o livro com "atenção" (as da análise e as da IA).
_WARNINGS = WARNING_NOTES + (LOW_CONFIDENCE_NOTE, NO_ANSWER_NOTE)
# Observações que a resposta da IA torna desatualizadas.
_RESOLVED_BY_AI = ("nome fora do padrão", "autor não encontrado", "o autor", "o título")

SYSTEM_PROMPT = """You identify books (including comics and manga) from limited clues.
Reply with ONE JSON object only, with exactly these keys:
  "title": the book's own title, WITHOUT volume number (string or null),
  "authors": list of real author names as "First Last" (list, may be empty),
  "series": series/collection name (string or null),
  "volume": volume number in the series (number or null),
  "year": publication year (integer or null),
  "publisher": publisher (string or null),
  "language": ISO 639-1 code of the book's text, e.g. "pt", "en" (string or null),
  "confidence": how sure you are, from 0 to 1 (number).
Rules:
- Trust the text of the first pages over the file name when they disagree.
- For volumes of a series (e.g. manga "One Punch Man - Vol 18"): series = collection
  name, volume = number, title = the volume's own title if it has one, otherwise the
  series name.
- Keep titles and names in the book's original language and spelling.
- "current_guess" was deduced from the file name and may be wrong (e.g. "v2" read as
  volume 2). If the book is not part of a series, use null for series and volume.
- Never invent: use null (or []) when the clues do not tell you."""


@dataclass
class AiBook:
    """A resposta da IA, já validada."""

    title: str = ""
    authors: list[str] = field(default_factory=list)
    series: str = ""
    volume: float | None = None
    year: int | None = None
    publisher: str = ""
    language: str = ""
    confidence: float = 0.0


def _text(value: object, limit: int = 300) -> str:
    return " ".join(str(value).split())[:limit] if isinstance(value, (str, int, float)) else ""


def parse_answer(data: dict) -> AiBook:
    """Converte o JSON da IA, ignorando tipos errados e valores sem sentido."""
    authors = data.get("authors")
    if isinstance(authors, str):
        authors = [authors]
    volume = data.get("volume")
    try:
        volume = float(volume) if volume not in (None, "") else None
    except (TypeError, ValueError):
        volume = None
    year = data.get("year")
    year = int(year) if isinstance(year, (int, float)) or (
        isinstance(year, str) and year.isdigit()) else None
    try:
        confidence = min(1.0, max(0.0, float(data.get("confidence", 0))))
    except (TypeError, ValueError):
        confidence = 0.0
    language = _text(data.get("language")).lower()
    return AiBook(
        title=_text(data.get("title")),
        authors=[_text(name) for name in authors or [] if _text(name)][:10],
        series=_text(data.get("series")),
        volume=volume if volume is not None and 0 <= volume < 100000 else None,
        year=year if year and 1000 <= year <= 2100 else None,
        publisher=_text(data.get("publisher")),
        language=language if re.fullmatch(r"[a-z]{2,3}", language) else "",
        confidence=confidence)


def book_clues(entry: BookEntry) -> dict:
    """O que a IA recebe sobre um livro (nada além disso sai do computador)."""
    info = read_pdf_info(entry.source)
    return {
        "file_name": entry.source.name,
        "pdf_metadata": {"title": info.title if not is_junk_title(info.title) else "",
                         "author": info.author if not is_junk_author(info.author) else ""},
        "pages": entry.pages,
        "current_guess": {"title": entry.title, "authors": entry.authors,
                          "series": entry.series, "volume": entry.series_index,
                          "year": entry.year},
        "first_pages_text": first_pages_text(entry.source),
    }


def ask_ai(client: GroqClient, entry: BookEntry,
           cancel: threading.Event | None = None) -> AiBook:
    clues = json.dumps(book_clues(entry), ensure_ascii=False)
    return parse_answer(client.chat_json(SYSTEM_PROMPT, clues, cancel))


def _other_standalone_book(entry: BookEntry, answer: AiBook) -> bool:
    """A IA reconheceu, com segurança, um livro avulso diferente da série deduzida.

    Ex.: "livro final v2.pdf" virou a série "livro final", vol. 2, mas a IA diz que é
    "O Alienista", sem série. Se a IA só repete o nome da série (Naruto), a série fica."""
    return (bool(answer.title) and not answer.series and answer.volume is None
            and answer.confidence >= LOW_CONFIDENCE and bool(entry.series)
            and entry.series.casefold() != answer.title.casefold())


def apply_answer(entry: BookEntry, answer: AiBook, fixed: dict[str, str],
                 unknown_author: str = "Unknown") -> None:
    """Põe a resposta no livro. Valores fixos ficam; o que a IA não sabe, também."""
    if answer.title and "title" not in fixed:
        entry.title, entry.title_origin = answer.title, "ia"
    if answer.authors and "author" not in fixed:
        entry.author, entry.author_origin = " & ".join(answer.authors), "ia"
    if answer.series and "series" not in fixed:
        entry.series = answer.series
    if answer.volume is not None and "volume" not in fixed:
        entry.series_index = answer.volume
        entry.series = entry.series or entry.title  # volume só existe dentro de uma série
    elif _other_standalone_book(entry, answer) and not {"series", "volume"} & fixed.keys():
        entry.series, entry.series_index = "", None  # o "volume" do nome do arquivo era engano
    if answer.year and "year" not in fixed:
        entry.year = answer.year
    if answer.publisher and "publisher" not in fixed:
        entry.publisher = answer.publisher
    if answer.language and "language" not in fixed:
        entry.language = answer.language
    # Reavalia os avisos com os dados novos.
    entry.notes = [note for note in entry.notes if not note.startswith(_RESOLVED_BY_AI)]
    normalize_authors(entry, unknown_author)
    entry.note(f"preenchido pela IA ({answer.confidence:.0%} de confiança)")
    if answer.confidence < LOW_CONFIDENCE:
        entry.note(LOW_CONFIDENCE_NOTE)
    flag_suspicious_values(entry)
    has_warning = any(note.startswith(_WARNINGS) for note in entry.notes)
    entry.status = Status.WARNING if has_warning else Status.READY


@dataclass
class AiReport:
    total: int = 0
    done: int = 0
    failed: int = 0
    cancelled: bool = False
    stopped: str = ""  # erro que interrompeu tudo (chave inválida, sem conexão...)
    errors: list[str] = field(default_factory=list)


def fill_with_ai(entries: list[BookEntry], client: GroqClient, fixed: dict[str, str],
                 unknown_author: str = "Unknown", progress: ProgressFn | None = None,
                 cancel: threading.Event | None = None) -> AiReport:
    """Consulta a IA para cada livro que vai ser importado, um por vez."""
    todo = [entry for entry in entries if entry.selected and entry.status in USABLE_STATUSES]
    report = AiReport(total=len(todo))
    for index, entry in enumerate(todo, start=1):
        if cancel is not None and cancel.is_set():
            report.cancelled = True
            break
        if progress:  # antes de perguntar: a resposta pode demorar (ou esperar o limite)
            progress(index - 1, report.total, f"{entry.source.name} (perguntando à IA)")
        try:
            apply_answer(entry, ask_ai(client, entry, cancel), fixed, unknown_author)
            report.done += 1
        except GroqError as exc:
            if str(exc) == "cancelado":
                report.cancelled = True
                break
            entry.note(f"{NO_ANSWER_NOTE}: {exc}")
            entry.status = Status.WARNING  # ficou só com o que o app deduziu: conferir
            report.failed += 1
            report.errors.append(f"{entry.source.name}: {exc}")
            if exc.fatal:
                report.stopped = str(exc)
                break
        if progress:
            progress(index, report.total, entry.source.name)
    return report
