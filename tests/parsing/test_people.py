"""Person names: recognising authors, splitting several, sort form."""
from src.parsing import people


def test_split_authors_variants():
    assert people.split_authors("Silva, João; Maria Souza") == ["João Silva", "Maria Souza"]
    assert people.split_authors("Ana Lima & Rui Dias") == ["Ana Lima", "Rui Dias"]
    assert people.split_authors("Ana Lima e Rui Dias") == ["Ana Lima", "Rui Dias"]
    assert people.split_authors("") == []


def test_split_authors_keeps_single_word_e():
    assert people.split_authors("Maria e Silva") == ["Maria e Silva"]


def test_author_sort():
    assert people.author_sort("João da Silva") == "Silva, João da"
    assert people.author_sort("Martin Luther King Jr.") == "King, Martin Luther Jr."
    assert people.author_sort("Platão") == "Platão"
    assert people.author_sort("Editora Abril") == "Editora Abril"
    assert people.author_sort("Silva, João") == "Silva, João"


def test_author_score():
    assert people.author_score("Ana Lima & Rui Dias") == 2
    assert people.author_score("Machado de Assis") == 1
    assert people.author_score("Guerra e Paz") == 0
    assert people.author_score("Romeu & Julieta") == 0  # one-word names are not people
