"""Volumes no nome do arquivo: 'Vol 18', 'Volume 41', 'v03', '- 03'."""
from __future__ import annotations

import re

VOL_WORD = r"(?:vol(?:ume)?|tomo|livro|book|parte|part|n[º°]|#)"
VOL_NUMBER = r"\d{1,4}(?:[.,]\d+)?"
# Uma parte inteira que é só o volume: "Vol 18", "Volume 41", "v03", "Tomo 2", "03".
VOL_PART = re.compile(
    rf"^(?:(?P<word>{VOL_WORD})\.?\s*|(?P<v>v)\.?\s*(?=\d))?(?P<num>{VOL_NUMBER})$", re.I)
# Volume no fim do texto, sem separador: "Naruto v03", "Berserk Vol. 41".
VOL_TRAILING = re.compile(
    rf"\s+(?:(?P<word>vol(?:ume)?|tomo)\.?\s*|(?P<v>v)(?=\d))(?P<num>{VOL_NUMBER})$", re.I)


def volume_from(match: re.Match) -> tuple[str, float]:
    """('Vol 18', 18.0) a partir de um match de volume; 'v03' e '03' viram 'Vol. 03'."""
    number = match.group("num")
    value = float(number.replace(",", "."))
    if match.group("word"):
        return match.group(0).strip(), value
    return f"Vol. {number}", value


def match_volume(text: str, bare_digits: int = 3) -> tuple[str, float] | None:
    """Se o texto inteiro é um volume, devolve (rótulo, número).

    Números sem prefixo só valem até `bare_digits` dígitos: "03" é volume,
    "2049" (em "Blade Runner - 2049") não.
    """
    match = VOL_PART.match(text.strip())
    if not match:
        return None
    if not (match.group("word") or match.group("v")) and \
            len(match.group("num").split(".")[0].split(",")[0]) > bare_digits:
        return None
    return volume_from(match)


def looks_like_volume(text: str) -> bool:
    """'Vol 01', 'Volume 41', 'v03' (com prefixo): serve para avisar quando o padrão pôs
    um volume no lugar do autor ou do título."""
    match = VOL_PART.match((text or "").strip())
    return bool(match and (match.group("word") or match.group("v")))
