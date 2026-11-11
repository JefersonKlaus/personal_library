from pathlib import Path

import pytest

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


def test_multiple_authors_in_file_name_win_over_title():
    """'Física Básica' parece nome de pessoa; 'Ana Lima & Rui Dias' parece mais."""
    for stem, author_first in [("Ana Lima e Rui Dias - Física Básica", True),
                               ("Física Básica - Ana Lima & Rui Dias", True),
                               ("Física Básica - Ana Lima e Rui Dias", False),
                               ("Ana Lima & Rui Dias - Física Básica", False)]:
        parsed = naming.parse_filename(stem, author_first)
        assert parsed.title == "Física Básica", stem
        assert naming.split_authors(parsed.author) == ["Ana Lima", "Rui Dias"], stem


def test_titles_with_e_or_ampersand_are_not_authors():
    for stem, title, author in [("Guerra e Paz - Liev Tolstói", "Guerra e Paz", "Liev Tolstói"),
                                ("Romeu & Julieta - William Shakespeare", "Romeu & Julieta",
                                 "William Shakespeare"),
                                ("Orgulho e Preconceito - Jane Austen", "Orgulho e Preconceito",
                                 "Jane Austen")]:
        parsed = naming.parse_filename(stem)
        assert (parsed.title, parsed.author) == (title, author)


def test_author_score():
    assert naming.author_score("Ana Lima & Rui Dias") == 2
    assert naming.author_score("Machado de Assis") == 1
    assert naming.author_score("Guerra e Paz") == 0
    assert naming.author_score("Romeu & Julieta") == 0  # nomes de uma palavra não são pessoas


# ---------------------------------------------------------------- volumes (modo automático)

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
    parsed = naming.parse_filename(stem)
    assert (parsed.title, parsed.author, parsed.series, parsed.series_index) == (
        title, author, series, index)


def test_numbers_that_are_not_volumes():
    assert naming.parse_filename("1984 - George Orwell").series_index is None
    assert naming.parse_filename("Blade Runner - 2049").series_index is None  # 4 dígitos
    assert naming.parse_filename("Machado de Assis - Dom Casmurro (1899)").year == 1899


# ---------------------------------------------------------------- "Como importar" (@parâmetros)

def _apply(config, stem):
    return naming.apply_spec(stem, naming.compile_spec(config))


@pytest.mark.parametrize("config, stem, title, author, series, index", [
    ("@name - @vol - @auth", "One Punch Man - Vol 18", "One Punch Man", "",
     "One Punch Man", 18),
    ("@name - @vol - @auth", "One Punch Man - Vol 18 - ONE & Yusuke Murata",
     "One Punch Man", "ONE & Yusuke Murata", "One Punch Man", 18),
    ("@name - @vol - @auth", "Spider-Man - Vol 2 - Stan Lee", "Spider-Man", "Stan Lee",
     "Spider-Man", 2),
    ("@name - @vol", "Naruto - 03", "Naruto", "", "Naruto", 3),
    ("@name @vol", "Naruto v03", "Naruto", "", "Naruto", 3),
    ("@name - @vol - @auth", "Naruto v03", "Naruto", "", "Naruto", 3),
    ("@name_@vol_@auth", "One_Punch_Man_Vol_18_ONE", "One Punch Man", "ONE",
     "One Punch Man", 18),
    ("@series - @vol - @name", "Harry Potter - 1 - A Pedra Filosofal", "A Pedra Filosofal", "",
     "Harry Potter", 1),
    ("@auth - @name", "Machado de Assis - Dom Casmurro", "Dom Casmurro", "Machado de Assis", "",
     None),
    ("@nome - @autor", "Dom Casmurro - Machado de Assis", "Dom Casmurro", "Machado de Assis", "",
     None),
])
def test_pattern_parameters(config, stem, title, author, series, index):
    parsed, matched = _apply(config, stem)
    assert matched
    assert (parsed.title, parsed.author, parsed.series, parsed.series_index) == (
        title, author, series, index)


@pytest.mark.parametrize("config", [
    "@name - @vol; @auth=ONE",        # depois de ;
    "@name - @vol @auth=ONE",         # no fim, sem ;
    "@name - @vol - @auth=ONE",       # no lugar da parte (o arquivo pode ou não ter)
    "@auth=ONE; @name - @vol",        # antes do padrão
])
def test_fixed_author_for_all_files(config):
    parsed, matched = _apply(config, "One Punch Man - Vol 18")
    assert matched and parsed.author == "ONE" and parsed.series == "One Punch Man"
    # Uma parte a mais: só segue o padrão quando o @auth=ONE está dentro dele (declara
    # a parte, cujo texto é trocado pelo valor fixo); depois de ';' ela não existe no
    # padrão. O valor fixo vale nos dois casos.
    parsed, matched = _apply(config, "One Punch Man - Vol 2 - Outro Nome")
    assert parsed.author == "ONE"
    assert matched == (";" not in config)


def test_fixed_values_without_pattern_use_automatic_mode():
    parsed, matched = _apply("@auth=ONE; @tags=mangá, shounen; @publisher=Panini; @lang=pt",
                             "One Punch Man - Vol 18")
    assert matched
    assert (parsed.title, parsed.author, parsed.series_index) == ("One Punch Man", "ONE", 18)
    assert (parsed.publisher, parsed.language, parsed.tags) == ("Panini", "pt",
                                                                ["mangá", "shounen"])


def test_fixed_name_with_volume_only_file_names():
    parsed, _ = _apply("@vol; @name=One Punch Man; @auth=ONE", "03")
    assert (parsed.title, parsed.series, parsed.series_index, parsed.author) == (
        "One Punch Man", "One Punch Man", 3, "ONE")


def test_each_parameter_fills_only_its_field():
    """O título é exatamente o @name; o volume vai para Vol. (número na série)."""
    parsed, _ = _apply("@name - @vol; @auth=One", "One Punch Man - Vol 16")
    assert (parsed.title, parsed.author, parsed.series_index) == ("One Punch Man", "One", 16)
    # Sem @series a série vem do @name: o Calibre descarta o volume de livro sem série.
    assert parsed.series == "One Punch Man" and parsed.series_from_name
    parsed, _ = _apply("@name - @vol; @series=Coleção OPM", "One Punch Man - Vol 16")
    assert (parsed.title, parsed.series, parsed.series_from_name) == (
        "One Punch Man", "Coleção OPM", False)
    parsed, _ = _apply("@name - @auth", "One Punch Man - Vol 01")
    assert (parsed.title, parsed.author, parsed.series, parsed.series_index) == (
        "One Punch Man", "Vol 01", "", None)  # o padrão manda; a interface avisa
    assert naming.looks_like_volume(parsed.author)


def test_looks_like_volume():
    assert naming.looks_like_volume("Vol 01") and naming.looks_like_volume("v03")
    assert not naming.looks_like_volume("ONE") and not naming.looks_like_volume("1984")


def test_pattern_year_and_skip():
    parsed, _ = _apply("@auth - @name (@year)", "Machado de Assis - Dom Casmurro (1899)")
    assert (parsed.title, parsed.year) == ("Dom Casmurro", 1899)
    parsed, _ = _apply("@skip - @name - @auth", "[Grupo] - Iracema - José de Alencar")
    assert (parsed.title, parsed.author) == ("Iracema", "José de Alencar")


def test_file_that_does_not_follow_the_pattern():
    parsed, matched = _apply("@name - @vol - @auth", "Machado de Assis - Dom Casmurro")
    assert not matched  # sem volume: cai no automático
    assert (parsed.title, parsed.author) == ("Dom Casmurro", "Machado de Assis")
    parsed, matched = _apply("@name - @vol - @auth=ONE", "Livro Sem Volume")
    assert matched and parsed.author == "ONE"  # partes do fim podem faltar


def test_previous_syntax_still_works():
    parsed, matched = _apply("NOME - VOL - AUTOR", "Naruto - 03 - Masashi Kishimoto")
    assert matched and (parsed.title, parsed.author, parsed.series_index) == (
        "Naruto", "Masashi Kishimoto", 3)


@pytest.mark.parametrize("text, message", [
    ("@foo - @name", "desconhecido: @foo"),
    ("@name - @name", "uma vez"),
    ("@name@vol", "delimitador"),
    ("@vol - @auth", "@name"),
    ("@auth=", "Falta o valor"),
    ("@vol=abc", "Volume fixo inválido"),
    ("@year=99", "Ano fixo inválido"),
    ("sem parametros", "parâmetros com @"),
    ("@name - @vol; @auth - @year", "um padrão"),
])
def test_invalid_configurations(text, message):
    with pytest.raises(naming.PatternError, match=message):
        naming.compile_spec(text)


def test_empty_configuration_means_automatic():
    assert naming.compile_spec("  ") is None
    parsed, matched = naming.apply_spec("One Punch Man - Vol 18", None)
    assert matched and parsed.series_index == 18
