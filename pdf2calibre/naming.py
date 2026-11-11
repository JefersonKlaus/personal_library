"""Limpeza de nomes: arquivo -> título/autor, e nomes seguros para pastas."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

_INVALID_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

# Marcas que sites de download deixam no nome do arquivo.
_NOISE_PATTERNS = [
    re.compile(r"\(?\s*\bz-?lib(?:rary)?(?:\.org)?\s*\)?", re.I),
    re.compile(r"\blibgen(?:\.\w+)?\b", re.I),
    re.compile(r"\bwww\.\S+", re.I),
    re.compile(r"[\(\[]\s*pdf\s*[\)\]]", re.I),
    re.compile(r"[\(\[]\s*(?:e-?book|ocr|scan(?:ned)?)\s*[\)\]]", re.I),
    re.compile(r"\s*[-–]\s*(?:copy|c[óo]pia)(?:\s*\(\d+\))?\s*$", re.I),
    re.compile(r"\s*\(\d{1,2}\)\s*$"),
]
_YEAR = re.compile(r"[\(\[]\s*((?:1[5-9]|20)\d{2})\s*[\)\]]")
_SEPARATOR = re.compile(r"\s+[-–—]\s+")

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
_ARTICLES = {"the", "a", "an", "o", "os", "as", "um", "uma", "el", "la", "los", "las", "le", "les"}


@dataclass
class ParsedName:
    """Resultado de interpretar um nome de arquivo."""

    title: str
    author: str = ""
    year: int | None = None


def normalize_text(text: str) -> str:
    """Unicode NFC, '_' vira espaço e espaços repetidos são colapsados."""
    text = unicodedata.normalize("NFC", text).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_noise(text: str) -> str:
    """Remove marcas de sites de download e sufixos de cópia."""
    for _ in range(2):  # a remoção de um padrão pode expor outro
        for pattern in _NOISE_PATTERNS:
            text = pattern.sub(" ", text)
    return normalize_text(text).strip(" -–._")


def extract_year(text: str) -> tuple[str, int | None]:
    """Extrai '(2019)' ou '[2019]' do texto; devolve (texto sem o ano, ano)."""
    match = None
    for match in _YEAR.finditer(text):
        pass  # fica com a última ocorrência
    if match is None:
        return text, None
    cleaned = normalize_text(text[: match.start()] + " " + text[match.end():])
    return cleaned, int(match.group(1))


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


def parse_filename(stem: str, author_first: bool = True) -> ParsedName:
    """Descobre título, autor e ano a partir do nome do arquivo (sem extensão).

    Reconhece "Autor - Título", "Título - Autor", "Título (Autor)" e
    "Título by/por Autor". Quando nada indica o autor, devolve só o título.
    """
    original = normalize_text(stem)
    text = strip_noise(original)
    text, year = extract_year(text)
    text = strip_noise(text)
    if not text:
        return ParsedName(title=original or "Sem título", year=year)

    parts = _SEPARATOR.split(text)
    if len(parts) >= 2:
        head, tail = parts[0], " - ".join(parts[1:])
        last, rest = parts[-1], " - ".join(parts[:-1])
        # (autor, título) para cada orientação possível
        preferred = (head, tail) if author_first else (last, rest)
        other = (last, rest) if author_first else (head, tail)
        if looks_like_person(preferred[0]) or not looks_like_person(other[0]):
            author, title = preferred
        else:
            author, title = other
        return ParsedName(title=title, author=author, year=year)

    match = re.match(r"^(?P<title>.+?)\s*[\(\[](?P<author>[^\)\]]+)[\)\]]$", text)
    if match and looks_like_person(match.group("author")):
        return ParsedName(match.group("title"), match.group("author"), year)

    match = re.match(r"^(?P<title>.+?)\s+(?:by|por)\s+(?P<author>.+)$", text, re.I)
    if match and looks_like_person(match.group("author")):
        return ParsedName(match.group("title"), match.group("author"), year)

    return ParsedName(title=text, year=year)


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
    """Forma de ordenação do Calibre: 'João da Silva' -> 'Silva, João da'."""
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


def title_sort(title: str) -> str:
    """'The Hobbit' -> 'Hobbit, The' (artigos iniciais vão para o fim)."""
    words = title.split()
    if len(words) >= 2 and words[0].lower() in _ARTICLES:
        return f"{' '.join(words[1:])}, {words[0]}"
    return title


def sanitize_component(text: str, max_len: int = 80, fallback: str = "_") -> str:
    """Deixa o texto válido como nome de pasta/arquivo no Windows, Linux e macOS."""
    text = re.sub(r"\s*:\s*", " - ", normalize_text(text))  # "Título: Sub" -> "Título - Sub"
    text = _INVALID_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if text.split(".")[0].upper() in _RESERVED_NAMES:
        text = f"_{text}"
    if len(text) > max_len:
        cut = text[:max_len]
        space = cut.rfind(" ")
        if space >= max_len // 2:
            cut = cut[:space]
        text = cut.strip(" .-_")
    return text or fallback


def book_stem(title: str, author: str, max_len: int = 80) -> str:
    """Nome do arquivo no estilo do Calibre: 'Título - Autor'."""
    title_part = sanitize_component(title, max_len, "Sem título")
    author_part = sanitize_component(author, max(20, max_len // 2), "Unknown")
    return f"{title_part} - {author_part}"


def natural_key(path: Path) -> list[object]:
    """Chave de ordenação natural: 'livro2' vem antes de 'livro10'."""
    return [int(piece) if piece.isdigit() else piece.casefold()
            for piece in re.split(r"(\d+)", str(path))]
