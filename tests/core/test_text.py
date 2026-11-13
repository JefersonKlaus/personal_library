"""Text: safe file names, sort names, natural order."""
from pathlib import Path

from src.core import text


def test_sanitize_replaces_invalid_characters():
    assert text.sanitize_component('A/B\\C:D?"') == "A_B_C - D__"
    assert text.sanitize_component("Título: Subtítulo") == "Título - Subtítulo"


def test_sanitize_handles_windows_reserved_and_trailing_dots():
    assert text.sanitize_component("CON") == "_CON"
    assert text.sanitize_component("Livro...  ") == "Livro"
    assert text.sanitize_component("   ", fallback="X") == "X"


def test_sanitize_truncates_on_word_boundary():
    result = text.sanitize_component("palavra " * 30, max_len=40)
    assert len(result) <= 40
    assert not result.endswith(" ")


def test_title_sort_moves_article():
    assert text.title_sort("The Hobbit") == "Hobbit, The"
    assert text.title_sort("Hobbit") == "Hobbit"
    assert text.title_sort("A") == "A"


def test_book_stem_is_title_dash_author():
    assert text.book_stem("Dom Casmurro", "Machado de Assis") == "Dom Casmurro - Machado de Assis"


def test_natural_key_orders_numbers():
    names = [Path("livro10.pdf"), Path("livro2.pdf"), Path("livro1.pdf")]
    assert [p.name for p in sorted(names, key=text.natural_key)] == [
        "livro1.pdf", "livro2.pdf", "livro10.pdf"]
