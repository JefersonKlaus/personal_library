import dataclasses
import json
import threading
from pathlib import Path

from src.importing import ai_metadata, analysis
from src.importing.groq_client import GroqError
from src.core.models import BookEntry, ImportOptions, Status


class FakeClient:
    """Responde por nome de arquivo; guarda o que foi enviado."""

    def __init__(self, answers):
        self.answers = answers
        self.sent = []

    def chat_json(self, system, user, cancel=None):
        clues = json.loads(user)
        self.sent.append(clues)
        answer = self.answers[clues["file_name"]]
        if isinstance(answer, Exception):
            raise answer
        return answer


def _entry(**kwargs):
    data = dict(source=Path("x.pdf"), title="Vol 18", author="Unknown", status=Status.WARNING,
                notes=["autor não encontrado"])
    data.update(kwargs)
    return BookEntry(**data)


def test_parse_answer_tolerates_bad_types():
    answer = ai_metadata.parse_answer({
        "title": "  One   Punch Man ", "authors": "ONE", "series": None, "volume": "18",
        "year": "2012", "publisher": 7, "language": "Português", "confidence": 3})
    assert (answer.title, answer.authors, answer.series, answer.volume) == (
        "One Punch Man", ["ONE"], "", 18.0)
    assert (answer.year, answer.publisher, answer.language, answer.confidence) == (
        2012, "7", "", 1.0)
    empty = ai_metadata.parse_answer({"year": 99999, "volume": "x", "confidence": "?"})
    assert (empty.year, empty.volume, empty.confidence, empty.authors) == (None, None, 0.0, [])


def test_apply_answer_fills_fields_and_clears_resolved_warnings():
    entry = _entry()
    answer = ai_metadata.AiBook(title="One Punch Man", authors=["ONE", "Yusuke Murata"],
                                volume=18, year=2019, publisher="Panini", language="pt",
                                confidence=0.9)
    ai_metadata.apply_answer(entry, answer, fixed={})
    assert (entry.title, entry.author) == ("One Punch Man", "ONE & Yusuke Murata")
    assert (entry.series, entry.series_index) == ("One Punch Man", 18)  # volume pede série
    assert (entry.year, entry.publisher, entry.language) == (2019, "Panini", "pt")
    assert entry.title_origin == entry.author_origin == "ia"
    assert entry.status is Status.READY  # o autor que faltava veio da IA
    assert entry.notes == ["preenchido pela IA (90% de confiança)"]


def test_fixed_values_and_unknown_fields_are_kept():
    entry = _entry(title="Naruto", author="Masashi Kishimoto", series="Naruto",
                   series_index=3.0, status=Status.READY, notes=[])
    ai_metadata.apply_answer(entry, ai_metadata.AiBook(
        title="NARUTO", authors=["Outro"], confidence=0.8), fixed={"author": "Masashi Kishimoto"})
    assert entry.author == "Masashi Kishimoto"  # @auth=... vence a IA
    assert entry.title == "NARUTO"
    assert (entry.series, entry.series_index) == ("Naruto", 3)  # a IA não sabia: ficou


def test_wrong_volume_guess_is_dropped_when_the_ai_knows_the_book():
    entry = _entry(title="livro final", series="livro final", series_index=2.0)
    answer = ai_metadata.AiBook(title="O Alienista", authors=["Machado de Assis"],
                                confidence=0.9)
    ai_metadata.apply_answer(entry, answer, fixed={})
    assert (entry.title, entry.series, entry.series_index) == ("O Alienista", "", None)
    unsure = _entry(title="livro final", series="livro final", series_index=2.0)
    ai_metadata.apply_answer(unsure, dataclasses.replace(answer, confidence=0.3), fixed={})
    assert (unsure.series, unsure.series_index) == ("livro final", 2)  # na dúvida, fica


def test_low_confidence_needs_review():
    entry = _entry(status=Status.READY, notes=[])
    ai_metadata.apply_answer(entry, ai_metadata.AiBook(title="Talvez", authors=["Alguém"],
                                                       confidence=0.3), fixed={})
    assert entry.status is Status.WARNING
    assert any("pouco confiante" in note for note in entry.notes)


def test_clues_sent_to_the_ai(make_pdf, tmp_path):
    """Só pistas em texto saem do computador (nunca o arquivo PDF)."""
    pdf = make_pdf(tmp_path / "One Punch Man - Vol 18.pdf", title="OPM", author="admin",
                   text="ONE & Yusuke Murata - Panini")
    entry = analysis.build_entry(pdf, ImportOptions())
    clues = ai_metadata.book_clues(entry)
    assert set(clues) == {"file_name", "pdf_metadata", "pages", "current_guess",
                          "first_pages_text"}
    assert clues["file_name"] == "One Punch Man - Vol 18.pdf"
    assert clues["pdf_metadata"] == {"title": "OPM", "author": ""}  # "admin" é lixo
    assert clues["current_guess"]["volume"] == 18
    assert "Yusuke Murata" in clues["first_pages_text"]


def test_fill_with_ai_one_by_one(make_pdf, tmp_path):
    names = ("A - Livro.pdf", "B - Livro.pdf", "C - Livro.pdf")
    entries = [analysis.build_entry(make_pdf(tmp_path / n, text=n), ImportOptions())
               for n in names]
    entries[2].selected = False  # desmarcado: não é enviado
    client = FakeClient({
        "A - Livro.pdf": {"title": "Livro A", "authors": ["Ana Lima"], "confidence": 0.9},
        "B - Livro.pdf": GroqError("resposta estranha"),
    })
    seen = []
    report = ai_metadata.fill_with_ai(entries, client, {},
                                      progress=lambda d, t, m: seen.append((d, t)))
    assert [c["file_name"] for c in client.sent] == ["A - Livro.pdf", "B - Livro.pdf"]
    assert (report.total, report.done, report.failed, report.stopped) == (2, 1, 1, "")
    assert entries[0].title == "Livro A" and entries[0].author == "Ana Lima"
    assert entries[1].status is Status.WARNING  # ficou com os dados do app: conferir
    assert any("IA não respondeu" in note for note in entries[1].notes)
    assert seen == [(0, 2), (1, 2), (1, 2), (2, 2)]  # antes e depois de cada pergunta


def test_fatal_error_stops_the_batch(make_pdf, tmp_path):
    entries = [analysis.build_entry(make_pdf(tmp_path / f"{n}.pdf", text=n), ImportOptions())
               for n in ("a", "b", "c")]
    client = FakeClient({"a.pdf": GroqError("Chave da API da Groq inválida.", fatal=True)})
    report = ai_metadata.fill_with_ai(entries, client, {})
    assert len(client.sent) == 1  # não insiste nos outros livros
    assert report.stopped == "Chave da API da Groq inválida."


def test_cancel(make_pdf, tmp_path):
    entries = [analysis.build_entry(make_pdf(tmp_path / "a.pdf"), ImportOptions())]
    cancel = threading.Event()
    cancel.set()
    report = ai_metadata.fill_with_ai(entries, FakeClient({}), {}, cancel=cancel)
    assert report.cancelled and report.done == 0
