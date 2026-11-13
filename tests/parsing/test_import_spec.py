""""Como importar": parameters, delimiters and fixed values."""
import pytest

from src.parsing import import_spec, volumes


# ---------------------------------------------------------------- "Como importar" (@parameters)

def _apply(config, stem):
    return import_spec.apply_spec(stem, import_spec.compile_spec(config))


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
    "@name - @vol; @auth=ONE",        # after ;
    "@name - @vol @auth=ONE",         # at the end, without ;
    "@name - @vol - @auth=ONE",       # in place of the part (the file may or may not have it)
    "@auth=ONE; @name - @vol",        # before the pattern
])
def test_fixed_author_for_all_files(config):
    parsed, matched = _apply(config, "One Punch Man - Vol 18")
    assert matched and parsed.author == "ONE" and parsed.series == "One Punch Man"
    # One extra part: it only follows the pattern when the @auth=ONE is inside it (it
    # declares the part, whose text is replaced by the fixed value); after ';' the part
    # does not exist in the pattern. The fixed value holds in both cases.
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
    """The title is exactly the @name; the volume goes to Vol. (number in the series)."""
    parsed, _ = _apply("@name - @vol; @auth=One", "One Punch Man - Vol 16")
    assert (parsed.title, parsed.author, parsed.series_index) == ("One Punch Man", "One", 16)
    # Without @series the series comes from @name: the library drops the volume of a book with no series.
    assert parsed.series == "One Punch Man" and parsed.series_from_name
    parsed, _ = _apply("@name - @vol; @series=Coleção OPM", "One Punch Man - Vol 16")
    assert (parsed.title, parsed.series, parsed.series_from_name) == (
        "One Punch Man", "Coleção OPM", False)
    parsed, _ = _apply("@name - @auth", "One Punch Man - Vol 01")
    assert (parsed.title, parsed.author, parsed.series, parsed.series_index) == (
        "One Punch Man", "Vol 01", "", None)  # the pattern rules; the interface warns
    assert volumes.looks_like_volume(parsed.author)


def test_pattern_year_and_skip():
    parsed, _ = _apply("@auth - @name (@year)", "Machado de Assis - Dom Casmurro (1899)")
    assert (parsed.title, parsed.year) == ("Dom Casmurro", 1899)
    parsed, _ = _apply("@skip - @name - @auth", "[Grupo] - Iracema - José de Alencar")
    assert (parsed.title, parsed.author) == ("Iracema", "José de Alencar")


def test_file_that_does_not_follow_the_pattern():
    parsed, matched = _apply("@name - @vol - @auth", "Machado de Assis - Dom Casmurro")
    assert not matched  # no volume: falls back to automatic
    assert (parsed.title, parsed.author) == ("Dom Casmurro", "Machado de Assis")
    parsed, matched = _apply("@name - @vol - @auth=ONE", "Livro Sem Volume")
    assert matched and parsed.author == "ONE"  # trailing parts may be missing


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
    with pytest.raises(import_spec.PatternError, match=message):
        import_spec.compile_spec(text)


def test_empty_configuration_means_automatic():
    assert import_spec.compile_spec("  ") is None
    parsed, matched = import_spec.apply_spec("One Punch Man - Vol 18", None)
    assert matched and parsed.series_index == 18


# ---------------------------------------------------------------- the example line

def test_describe_pattern_says_what_went_where():
    spec = import_spec.compile_spec("@name - @vol; @auth=ONE")
    preview = import_spec.describe_pattern("One Punch Man - Vol 18", spec, True)
    assert preview.ok
    assert preview.text == ("«One Punch Man - Vol 18» → Título: One Punch Man · Autor: ONE (fixo)"
                            " · Vol.: 18 · Série: One Punch Man (de @name: a biblioteca só"
                            " guarda o volume dentro de uma série)")


def test_describe_pattern_warns_about_misplaced_volumes_and_other_names():
    spec = import_spec.compile_spec("@name - @auth")
    volume_as_author = import_spec.describe_pattern("One Punch Man - Vol 01", spec, True)
    assert not volume_as_author.ok and "(parece um volume: use @vol)" in volume_as_author.text
    outside = import_spec.describe_pattern("Machado de Assis - Dom Casmurro",
                                           import_spec.compile_spec("@name - @vol - @auth"), True)
    assert not outside.ok
    assert outside.text.startswith("«Machado de Assis - Dom Casmurro» não segue o padrão")
