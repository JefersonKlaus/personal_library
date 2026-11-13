"""Automatic mode: title, author, year and volume from the file name."""
import pytest

from src.parsing import filename_parser, people


def test_parse_author_dash_title():
    parsed = filename_parser.parse_filename("Machado de Assis - Dom Casmurro")
    assert (parsed.author, parsed.title) == ("Machado de Assis", "Dom Casmurro")


def test_parse_title_dash_author_when_author_first_is_false():
    parsed = filename_parser.parse_filename("Dom Casmurro - Machado de Assis", author_first=False)
    assert (parsed.author, parsed.title) == ("Machado de Assis", "Dom Casmurro")


def test_parse_swaps_when_only_other_side_looks_like_person():
    parsed = filename_parser.parse_filename("o senhor dos anéis - J. R. R. Tolkien")
    assert parsed.author == "J. R. R. Tolkien"
    assert parsed.title == "o senhor dos anéis"


def test_parse_parentheses_author_and_year():
    parsed = filename_parser.parse_filename("Grande Sertão (Guimarães Rosa) (1956)")
    assert parsed.year == 1956
    assert parsed.author == "Guimarães Rosa"
    assert parsed.title == "Grande Sertão"


def test_parse_by_keyword():
    parsed = filename_parser.parse_filename("Clean Code by Robert Martin")
    assert (parsed.title, parsed.author) == ("Clean Code", "Robert Martin")


def test_parse_removes_download_noise():
    parsed = filename_parser.parse_filename("Livro_Teste (z-lib.org) (1)")
    assert parsed.title == "Livro Teste"
    assert parsed.author == ""


def test_parse_only_title_when_no_hint():
    parsed = filename_parser.parse_filename("apostila de física")
    assert parsed.title == "apostila de física"
    assert parsed.author == ""


def test_multiple_authors_in_file_name_win_over_title():
    """'Física Básica' looks like a person name; 'Ana Lima & Rui Dias' looks more like one."""
    for stem, author_first in [("Ana Lima e Rui Dias - Física Básica", True),
                               ("Física Básica - Ana Lima & Rui Dias", True),
                               ("Física Básica - Ana Lima e Rui Dias", False),
                               ("Ana Lima & Rui Dias - Física Básica", False)]:
        parsed = filename_parser.parse_filename(stem, author_first)
        assert parsed.title == "Física Básica", stem
        assert people.split_authors(parsed.author) == ["Ana Lima", "Rui Dias"], stem


def test_titles_with_e_or_ampersand_are_not_authors():
    for stem, title, author in [("Guerra e Paz - Liev Tolstói", "Guerra e Paz", "Liev Tolstói"),
                                ("Romeu & Julieta - William Shakespeare", "Romeu & Julieta",
                                 "William Shakespeare"),
                                ("Orgulho e Preconceito - Jane Austen", "Orgulho e Preconceito",
                                 "Jane Austen")]:
        parsed = filename_parser.parse_filename(stem)
        assert (parsed.title, parsed.author) == (title, author)


# ---------------------------------------------------------------- volumes (automatic mode)

@pytest.mark.parametrize("stem, title, author, series, index", [
    ("One Punch Man - Vol 18", "One Punch Man", "", "One Punch Man", 18),
    ("One Punch Man - Vol 18 - ONE", "One Punch Man", "ONE", "One Punch Man", 18),
    ("ONE - One Punch Man - Vol 18", "One Punch Man", "ONE", "One Punch Man", 18),
    ("Naruto v03", "Naruto", "", "Naruto", 3),
    ("Naruto - 03", "Naruto", "", "Naruto", 3),
    ("Berserk - Volume 41 - Kentaro Miura", "Berserk", "Kentaro Miura", "Berserk", 41),
    ("Berserk Vol. 41 - Kentaro Miura", "Berserk", "Kentaro Miura", "Berserk", 41),
    ("One Punch Man - Vol 18 (2019) (z-lib.org)", "One Punch Man", "", "One Punch Man",
     18),
])
def test_automatic_mode_finds_volumes(stem, title, author, series, index):
    parsed = filename_parser.parse_filename(stem)
    assert (parsed.title, parsed.author, parsed.series, parsed.series_index) == (
        title, author, series, index)


def test_numbers_that_are_not_volumes():
    assert filename_parser.parse_filename("1984 - George Orwell").series_index is None
    assert filename_parser.parse_filename("Blade Runner - 2049").series_index is None  # 4 digits
    assert filename_parser.parse_filename("Machado de Assis - Dom Casmurro (1899)").year == 1899
