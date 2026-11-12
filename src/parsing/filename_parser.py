"""Modo automático: deduz título, autor, ano e volume do nome do arquivo."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .people import author_score, looks_like_person
from ..core.text import extract_year, normalize_text, strip_noise
from .volumes import VOL_TRAILING, match_volume, volume_from

SEPARATOR = re.compile(r"\s+[-–—]\s+")  # " - " entre as partes do nome


@dataclass
class ParsedName:
    """Resultado de interpretar um nome de arquivo."""

    title: str
    author: str = ""
    year: int | None = None
    series: str = ""
    series_index: float | None = None  # número do volume
    publisher: str = ""
    language: str = ""
    tags: list[str] = field(default_factory=list)
    series_from_name: bool = False  # série veio do @name (há volume, mas não @series)


def _title_and_author(text: str, author_first: bool) -> tuple[str, str]:
    """Separa título e autor de um texto já limpo (sem ano nem volume)."""
    parts = SEPARATOR.split(text)
    if len(parts) >= 2:
        head, tail = parts[0], " - ".join(parts[1:])
        last, rest = parts[-1], " - ".join(parts[:-1])
        # (autor, título) para cada orientação possível
        preferred = (head, tail) if author_first else (last, rest)
        other = (last, rest) if author_first else (head, tail)
        # A orientação escolhida pelo usuário vence, a não ser que o outro lado
        # pareça mais com autor(es) (ex.: "Física Básica - Ana Lima & Rui Dias").
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
    """Acha o volume e a obra a que ele pertence: (obra, resto, (rótulo, número)).

    O volume fica colado na obra: em "One Punch Man - Vol 18 - ONE" e em
    "ONE - One Punch Man - Vol 18" a obra é a parte logo antes do volume, e o
    que sobra ("ONE") é o autor.
    """
    parts = SEPARATOR.split(text)
    if len(parts) >= 2:
        for index in range(len(parts) - 1, -1, -1):  # o volume costuma vir no fim
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
    """Partes deduzidas do nome do arquivo, ainda em texto: title, author, year, volume."""
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
    """Monta o resultado a partir das partes em texto: cada parte vai para o seu campo.

    O título é exatamente o @name. O volume vira o número na série; sem @series, a
    série é o próprio @name, porque a biblioteca só guarda o número dentro de uma série
    (sem série ela descarta o volume).
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
    """Descobre título, autor, ano e volume a partir do nome do arquivo (sem extensão).

    Reconhece "Autor - Título", "Título - Autor", "Título (Autor)", "Título by/por
    Autor" e volumes ("Vol 18", "Volume 41", "v03", "- 03"). Quando nada indica o
    autor, devolve só o título.
    """
    return compose(automatic_values(stem, author_first))
