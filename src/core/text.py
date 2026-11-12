"""Texto: limpeza de nomes de arquivo, comparação sem acentos e nomes seguros de arquivo."""
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
_ARTICLES = {"the", "a", "an", "o", "os", "as", "um", "uma", "el", "la", "los", "las", "le", "les"}


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


def fold(text: str) -> str:
    """Minúsculas e sem acentos: 'Cortiço' e 'cortico' se encontram."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


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
    """Nome de arquivo de um livro: 'Título - Autor'."""
    title_part = sanitize_component(title, max_len, "Sem título")
    author_part = sanitize_component(author, max(20, max_len // 2), "Unknown")
    return f"{title_part} - {author_part}"


def natural_key(path: Path) -> list[object]:
    """Chave de ordenação natural: 'livro2' vem antes de 'livro10'."""
    return [int(piece) if piece.isdigit() else piece.casefold()
            for piece in re.split(r"(\d+)", str(path))]


def html_to_text(value: str) -> str:
    """Descrições de livros vêm em HTML; a tela mostra só o texto."""
    value = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", value or "")
    value = html.unescape(re.sub(r"<[^>]+>", "", value))
    return re.sub(r"\n{3,}", "\n\n", value).strip()
