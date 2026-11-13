"""Text: cleaning up file names, accent-insensitive comparison and safe file names."""
from __future__ import annotations

import html
import re
import unicodedata
from pathlib import Path

_INVALID_CHARS = re.compile(r'[<>"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
# Marks that download sites leave in the file name.
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
_ARTICLES = {"the", "a", "an", "o", "os", "as", "um", "uma", "el", "la", "los", "las", "le", "les"}


def normalize_text(text: str) -> str:
    """Unicode NFC, '_' becomes a space and repeated spaces are collapsed."""
    text = unicodedata.normalize("NFC", text).replace("_", " ")
    return re.sub(r"\s+", " ", text).strip()


def strip_noise(text: str) -> str:
    """Removes marks left by download sites and copy suffixes."""
    for _ in range(2):  # removing one pattern can expose another
        for pattern in _NOISE_PATTERNS:
            text = pattern.sub(" ", text)
    return normalize_text(text).strip(" -–._")


def extract_year(text: str) -> tuple[str, int | None]:
    """Extracts '(2019)' or '[2019]' from the text; returns (text without the year, year)."""
    match = None
    for match in _YEAR.finditer(text):
        pass  # keeps the last occurrence
    if match is None:
        return text, None
    cleaned = normalize_text(text[: match.start()] + " " + text[match.end():])
    return cleaned, int(match.group(1))


def fold(text: str) -> str:
    """Lower case and without accents: 'Cortiço' and 'cortico' match."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def title_sort(title: str) -> str:
    """'The Hobbit' -> 'Hobbit, The' (leading articles go to the end)."""
    words = title.split()
    if len(words) >= 2 and words[0].lower() in _ARTICLES:
        return f"{' '.join(words[1:])}, {words[0]}"
    return title


def sanitize_component(text: str, max_len: int = 80, fallback: str = "_") -> str:
    """Makes the text valid as a folder/file name on Windows, Linux and macOS."""
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
    """File name of a book: 'Title - Author'."""
    title_part = sanitize_component(title, max_len, "Sem título")
    author_part = sanitize_component(author, max(20, max_len // 2), "Unknown")
    return f"{title_part} - {author_part}"


def natural_key(path: Path) -> list[object]:
    """Natural sort key: 'livro2' comes before 'livro10'."""
    return [int(piece) if piece.isdigit() else piece.casefold()
            for piece in re.split(r"(\d+)", str(path))]


def html_to_text(value: str) -> str:
    """Book descriptions come as HTML; the screen shows only the text."""
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value or "")
    value = html.unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"\n{3,}", "\n\n", value).strip()
