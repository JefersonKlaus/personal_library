from pathlib import Path

from pdf2calibre import naming


def test_sanitize_replaces_invalid_characters():
    assert naming.sanitize_component('A/B\\C:D?"') == "A_B_C - D__"
    assert naming.sanitize_component("Título: Subtítulo") == "Título - Subtítulo"


def test_sanitize_handles_windows_reserved_and_trailing_dots():
    assert naming.sanitize_component("CON") == "_CON"
    assert naming.sanitize_component("Livro...  ") == "Livro"
    assert naming.sanitize_component("   ", fallback="X") == "X"


def test_sanitize_truncates_on_word_boundary():
    result = naming.sanitize_component("palavra " * 30, max_len=40)
    assert len(result) <= 40
    assert not result.endswith(" ")


def test_parse_author_dash_title():
    parsed = naming.parse_filename("Machado de Assis - Dom Casmurro")
    assert (parsed.author, parsed.title) == ("Machado de Assis", "Dom Casmurro")


def test_parse_title_dash_author_when_author_first_is_false():
    parsed = naming.parse_filename("Dom Casmurro - Machado de Assis", author_first=False)
    assert (parsed.author, parsed.title) == ("Machado de Assis", "Dom Casmurro")


def test_parse_swaps_when_only_other_side_looks_like_person():
    parsed = naming.parse_filename("o senhor dos anéis - J. R. R. Tolkien")
    assert parsed.author == "J. R. R. Tolkien"
    assert parsed.title == "o senhor dos anéis"


def test_parse_parentheses_author_and_year():
    parsed = naming.parse_filename("Grande Sertão (Guimarães Rosa) (1956)")
    assert parsed.year == 1956
    assert parsed.author == "Guimarães Rosa"
    assert parsed.title == "Grande Sertão"


def test_parse_by_keyword():
    parsed = naming.parse_filename("Clean Code by Robert Martin")
    assert (parsed.title, parsed.author) == ("Clean Code", "Robert Martin")


def test_parse_removes_download_noise():
    parsed = naming.parse_filename("Livro_Teste (z-lib.org) (1)")
    assert parsed.title == "Livro Teste"
    assert parsed.author == ""


def test_parse_only_title_when_no_hint():
    parsed = naming.parse_filename("apostila de física")
    assert parsed.title == "apostila de física"
    assert parsed.author == ""


def test_split_authors_variants():
    assert naming.split_authors("Silva, João; Maria Souza") == ["João Silva", "Maria Souza"]
    assert naming.split_authors("Ana Lima & Rui Dias") == ["Ana Lima", "Rui Dias"]
    assert naming.split_authors("Ana Lima e Rui Dias") == ["Ana Lima", "Rui Dias"]
    assert naming.split_authors("") == []


def test_split_authors_keeps_single_word_e():
    assert naming.split_authors("Maria e Silva") == ["Maria e Silva"]


def test_author_sort():
    assert naming.author_sort("João da Silva") == "Silva, João da"
    assert naming.author_sort("Martin Luther King Jr.") == "King, Martin Luther Jr."
    assert naming.author_sort("Platão") == "Platão"
    assert naming.author_sort("Editora Abril") == "Editora Abril"
    assert naming.author_sort("Silva, João") == "Silva, João"


def test_title_sort_moves_article():
    assert naming.title_sort("The Hobbit") == "Hobbit, The"
    assert naming.title_sort("Hobbit") == "Hobbit"
    assert naming.title_sort("A") == "A"


def test_book_stem_follows_calibre_style():
    assert naming.book_stem("Dom Casmurro", "Machado de Assis") == "Dom Casmurro - Machado de Assis"


def test_natural_key_orders_numbers():
    names = [Path("livro10.pdf"), Path("livro2.pdf"), Path("livro1.pdf")]
    assert [p.name for p in sorted(names, key=naming.natural_key)] == [
        "livro1.pdf", "livro2.pdf", "livro10.pdf"]
