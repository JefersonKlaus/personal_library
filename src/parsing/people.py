"""Nomes de pessoas: reconhecer autores, separar vários e a forma de ordenação."""
from __future__ import annotations

import re

from ..core.text import normalize_text

# Palavras minúsculas aceitas dentro de nomes de pessoas.
_PARTICLES = {
    "de", "da", "do", "dos", "das", "del", "della", "di", "du",
    "van", "von", "der", "den", "la", "le", "el", "bin", "ibn", "al",
}
_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "filho", "neto", "junior", "júnior", "sobrinho"}
_CORPORATE = re.compile(
    r"\b(ltd|ltda|inc|llc|corp|gmbh|editora|press|university|universidade|"
    r"instituto|institute|association|associação|company)\b",
    re.I,
)


def looks_like_person(text: str) -> bool:
    """Heurística: 1 a 5 palavras capitalizadas, sem números."""
    words = text.replace(".", ". ").split()
    if not 1 <= len(words) <= 5 or len(text) > 60:
        return False
    if any(char.isdigit() for char in text):
        return False
    for word in words:
        base = word.strip(".,")
        if not base or base.lower() in _PARTICLES:
            continue
        if not base[0].isupper():
            return False
    return True


_PEOPLE_SEPARATOR = re.compile(r"\s*;\s*|\s+&\s+|\s+and\s+|\s+e\s+", re.I)


def author_score(text: str) -> int:
    """Quanto o texto parece ser autor(es): 2 = várias pessoas, 1 = uma, 0 = não.

    "Ana Lima e Rui Dias" vale 2. Cada nome precisa ter 2+ palavras, senão
    títulos como "Guerra e Paz" ou "Romeu & Julieta" passariam por autores.
    """
    parts = [part for part in _PEOPLE_SEPARATOR.split(text) if part.strip()]
    if len(parts) >= 2 and all(len(part.split()) >= 2 and looks_like_person(part)
                               for part in parts):
        return 2
    return 1 if looks_like_person(text) else 0


def display_name(name: str) -> str:
    """'Silva, João' -> 'João Silva'. Outros nomes ficam como estão."""
    name = normalize_text(name)
    if name.count(",") == 1:
        last, first = (part.strip() for part in name.split(","))
        small = len(first.split()) <= 3 and len(last.split()) <= 3
        if first and last and small and first.strip(".").lower() not in _SUFFIXES:
            return f"{first} {last}"
    return name


def split_authors(raw: str) -> list[str]:
    """Separa vários autores ('A; B', 'A & B', 'A and B', 'Ana Lima e Rui Dias')."""
    raw = normalize_text(raw)
    if not raw:
        return []
    pieces: list[str] = []
    for chunk in re.split(r"\s*;\s*|\s+&\s+|\s+and\s+", raw, flags=re.I):
        sub = re.split(r"\s+e\s+", chunk)
        multi = len(sub) > 1 and all(
            len(item.split()) >= 2 and looks_like_person(item) for item in sub
        )
        pieces.extend(sub if multi else [chunk])
    return [display_name(piece.strip(" ,")) for piece in pieces if piece.strip(" ,")]


def author_sort(name: str) -> str:
    """Forma de ordenação: 'João da Silva' -> 'Silva, João da'."""
    name = normalize_text(name)
    if not name or "," in name or _CORPORATE.search(name):
        return name
    tokens = name.split()
    suffix: list[str] = []
    while len(tokens) > 1 and tokens[-1].strip(".").lower() in _SUFFIXES:
        suffix.insert(0, tokens.pop())
    if len(tokens) == 1:
        return name
    last = tokens.pop()
    result = f"{last}, {' '.join(tokens)}"
    return f"{result} {' '.join(suffix)}" if suffix else result
