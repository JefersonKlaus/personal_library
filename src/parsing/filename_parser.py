"""Automatic mode: works out title, author, year and volume from the file name."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..core.text import extract_year, normalize_text, strip_noise
from .people import author_score, looks_like_person
from .volumes import VOL_TRAILING, match_volume, volume_from

SEPARATOR = re.compile(r"\s+[-–—]\s+")  # " - " between the parts of the name


@dataclass
class ParsedName:
    """Result of interpreting a file name."""

    title: str
    author: str = ""
    year: int | None = None
    series: str = ""
    series_index: float | None = None  # number of the volume
    publisher: str = ""
    language: str = ""
    tags: list[str] = field(default_factory=list)
    series_from_name: bool = False  # series came from @name (there is a volume, but no @series)


def _title_and_author(text: str, author_first: bool) -> tuple[str, str]:
    """Splits title and author out of already cleaned text (no year, no volume)."""
    parts = SEPARATOR.split(text)
    if len(parts) >= 2:
        head, tail = parts[0], " - ".join(parts[1:])
        last, rest = parts[-1], " - ".join(parts[:-1])
        # (author, title) for each possible orientation
        preferred = (head, tail) if author_first else (last, rest)
        other = (last, rest) if author_first else (head, tail)
        # The orientation chosen by the user wins, unless the other side
        # looks more like author(s) (e.g. "Física Básica - Ana Lima & Rui Dias").
        if author_score(preferred[0]) >= author_score(other[0]):
            author, title = preferred
        else:
            author, title = other
        return title, author

    match = re.match(r"^(?P<title>.+?)\s*[\(\[](?P<author>[^\)\]]+)[\)\]]$", text)
    if match and looks_like_person(match.group("author")):
        return match.group("title"), match.group("author")

    match = re.match(r"^(?P<title>.+?)\s+(?:by|por)\s+(?P<author>.+)$", text, re.I)
    if match and looks_like_person(match.group("author")):
        return match.group("title"), match.group("author")
    return text, ""


def _split_volume(text: str) -> tuple[str, str, tuple[str, float]] | None:
    """Finds the volume and the work it belongs to: (work, rest, (label, number)).

    The volume sits right next to the work: in "One Punch Man - Vol 18 - ONE" and in
    "ONE - One Punch Man - Vol 18" the work is the part just before the volume, and
    what is left ("ONE") is the author.
    """
    parts = SEPARATOR.split(text)
    if len(parts) >= 2:
        for index in range(len(parts) - 1, -1, -1):  # the volume usually comes at the end
            volume = match_volume(parts[index])
            if volume:
                name_index = index - 1 if index > 0 else index + 1
                others = [part for i, part in enumerate(parts) if i not in (index, name_index)]
                return parts[name_index], " & ".join(others), volume
    for index, part in enumerate(parts):  # "Naruto v03", "Berserk Vol. 41 - Kentaro Miura"
        match = VOL_TRAILING.search(part)
        if match and match.start() > 0:
            others = [other for i, other in enumerate(parts) if i != index]
            return part[:match.start()].strip(), " & ".join(others), volume_from(match)
    return None


def automatic_values(stem: str, author_first: bool) -> dict[str, str]:
    """Parts worked out from the file name, still as text: title, author, year, volume."""
    original = normalize_text(stem)
    text = strip_noise(original)
    text, year = extract_year(text)
    text = strip_noise(text)
    values = {"year": str(year)} if year else {}
    if not text:
        values["title"] = original or "Sem título"
        return values
    found = _split_volume(text)
    if found is None or not found[0]:
        values["title"], values["author"] = _title_and_author(text, author_first)
    else:
        values["title"], values["author"], (values["volume"], _number) = found
    return values


def compose(values: dict[str, str]) -> ParsedName:
    """Builds the result from the text parts: each part goes to its own field.

    The title is exactly the @name. The volume becomes the number in the series; without
    @series, the series is the @name itself, because the library only keeps the number
    inside a series (with no series it drops the volume).
    """
    name = values.get("title", "").strip()
    series = values.get("series", "").strip()
    year_digits = re.sub(r"\D", "", values.get("year", ""))
    parsed = ParsedName(
        title=name or series or "Sem título", author=values.get("author", "").strip(),
        year=int(year_digits) if len(year_digits) == 4 else None, series=series,
        publisher=values.get("publisher", "").strip(),
        language=values.get("language", "").strip(),
        tags=[tag.strip() for tag in values.get("tags", "").split(",") if tag.strip()])
    volume = match_volume(values["volume"], bare_digits=4) if values.get("volume") else None
    if volume is not None:
        parsed.series_index = volume[1]
        if not series:
            parsed.series, parsed.series_from_name = parsed.title, True
    return parsed


def parse_filename(stem: str, author_first: bool = True) -> ParsedName:
    """Works out title, author, year and volume from the file name (without extension).

    Recognises "Autor - Título", "Título - Autor", "Título (Autor)", "Título by/por
    Autor" and volumes ("Vol 18", "Volume 41", "v03", "- 03"). When nothing points to
    the author, returns only the title.
    """
    return compose(automatic_values(stem, author_first))
