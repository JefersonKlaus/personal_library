import json
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

from personal_library import analysis, importer
from personal_library.library.cli import AddResult
from personal_library.models import ImportOptions, Status

NS = {"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf"}


class FakeCli:
    """Registra o que seria enviado à ferramenta da biblioteca."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.added = []  # (entry, arquivo, opf existe?, capa, permite duplicado?)
        self.removed = []

    def add_book(self, library, book_file, entry, tags, cover=None, allow_duplicate=False):
        opf = book_file.with_suffix(".opf")
        self.added.append({"entry": entry, "file": book_file, "opf": opf.read_text("utf-8")
                           if opf.is_file() else None, "cover": cover, "tags": tags,
                           "allow_duplicate": allow_duplicate})
        return self.results.pop(0) if self.results else AddResult(True, [len(self.added)])

    def remove_books(self, library, ids):
        self.removed.append(ids)
        return True, ""


def _entries(tmp_path, make_pdf, names=("Autor Um - Livro Um", "Autor Dois - Livro Dois",
                                        "Autor Tres - Livro Tres"), **options):
    src = tmp_path / "src"
    for number, name in enumerate(names):
        make_pdf(src / f"{name}.pdf", text=str(number))
    opts = ImportOptions(workers=1, **options)
    return analysis.build_entries(analysis.find_pdfs([src]), opts), opts


def test_each_book_is_staged_with_opf_and_cover(tmp_path, make_pdf, make_library):
    root = make_library(tmp_path / "Biblioteca")
    entries, options = _entries(tmp_path, make_pdf, tags=["importado"])
    cli = FakeCli()
    report = importer.import_books(entries, root, options, cli, records_dir=tmp_path / "rec")
    assert report.added == 3
    first = cli.added[0]
    # a ferramenta recebe "Título - Autor.pdf" com o OPF de mesmo nome e a capa ao lado
    assert first["file"].name == "Livro Dois - Autor Dois.pdf"  # ordem natural dos arquivos
    assert first["cover"] is not None and first["cover"].name == "cover.jpg"
    opf = ET.fromstring(first["opf"])
    assert opf.find(".//dc:title", NS).text == "Livro Dois"
    assert first["tags"] == ["importado"]
    assert not first["file"].exists()  # pasta temporária apagada no fim
    assert all(e.status is Status.DONE for e in entries)


def test_results_update_each_book_and_are_recorded(tmp_path, make_pdf, make_library):
    root = make_library(tmp_path / "Biblioteca")
    entries, options = _entries(tmp_path, make_pdf)
    cli = FakeCli([AddResult(True, [21]),
                   AddResult(False, message="já existe na biblioteca", duplicate=True),
                   AddResult(False, message="banco travado")])
    records = tmp_path / "records"
    report = importer.import_books(entries, root, options, cli, records_dir=records)
    assert (report.added, report.existing, report.failed) == (1, 1, 1)
    assert [e.status for e in entries] == [Status.DONE, Status.EXISTS, Status.FAILED]
    assert report.errors == ["Livro Um: banco travado"]
    record = importer.latest_import(root, records)
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["ids"] == [21] and data["library"] == str(root.resolve())
    assert importer.latest_import(tmp_path / "outra", records) is None


def test_changed_pdf_fails_alone(tmp_path, make_pdf, make_library):
    """O PDF mudou depois da análise: só ele falha, os outros são importados."""
    root = make_library(tmp_path / "Biblioteca")
    entries, options = _entries(tmp_path, make_pdf)
    entries[0].source.write_bytes(entries[0].source.read_bytes() + b"\n%extra")
    report = importer.import_books(entries, root, options, FakeCli(),
                                   records_dir=tmp_path / "rec")
    assert (report.added, report.failed) == (2, 1)
    assert entries[0].status is Status.FAILED and "diferente" in entries[0].notes[-1]


def test_cancel_and_progress(tmp_path, make_pdf, make_library):
    root = make_library(tmp_path / "Biblioteca")
    entries, options = _entries(tmp_path, make_pdf)
    calls = []
    importer.import_books(entries, root, options, FakeCli(), records_dir=tmp_path / "rec",
                          progress=lambda d, t, m: calls.append((d, t)))
    assert calls == [(1, 3), (2, 3), (3, 3)]
    entries, options = _entries(tmp_path / "b", make_pdf)
    cancel = threading.Event()
    cancel.set()
    report = importer.import_books(entries, root, options, FakeCli(), cancel=cancel,
                                   records_dir=tmp_path / "rec")
    assert report.cancelled and report.added == 0


def test_import_with_nothing_selected(tmp_path, make_pdf):
    entries, options = _entries(tmp_path, make_pdf)
    for entry in entries:
        entry.selected = False
    report = importer.import_books(entries, tmp_path, options, FakeCli())
    assert report.total == 0 and report.record is None


def test_volumes_already_in_library_are_skipped(tmp_path, make_pdf, make_library):
    root = make_library(tmp_path / "Biblioteca")  # tem "Dom Casmurro" em Clássicos [1]
    entries, options = _entries(
        tmp_path, make_pdf, names=("Dom Casmurro - 1", "Dom Casmurro - 2"),
        filename_pattern="@name - @vol; @auth=Machado de Assis; @series=Clássicos")
    cli = FakeCli()
    report = importer.import_books(entries, root, options, cli, records_dir=tmp_path / "rec")
    assert [added["entry"].series_index for added in cli.added] == [2]
    assert cli.added[0]["allow_duplicate"]  # volumes: a biblioteca só compara título + autor
    assert (report.added, report.existing) == (1, 1)
    vol1 = next(e for e in entries if e.series_index == 1)
    assert vol1.status is Status.EXISTS and "mesmo título, autor e volume" in vol1.notes[-1]


def test_opf_of_an_imported_book(tmp_path):
    from personal_library.models import BookEntry

    entry = BookEntry(Path("x.pdf"), title="One Punch Man", author="ONE", year=2012,
                      series="One Punch Man", series_index=18.0, publisher="Panini",
                      language="pt", sha256="ab" * 32)
    data = importer.entry_opf_data(entry, ["mangá"])
    # meio-dia UTC: continua 2012 em qualquer fuso (meia-noite viraria 2011 no Brasil)
    assert data.pubdate == "2012-01-01T12:00:00+00:00"
    assert (data.series, data.series_index, data.publisher, data.tags) == (
        "One Punch Man", 18.0, "Panini", ["mangá"])


def test_undo_import_removes_ids(tmp_path):
    record = importer.write_import_record(tmp_path, tmp_path / "lib", [3, 4], ["A", "B"])
    cli = FakeCli()
    assert importer.undo_import(record, cli) == (2, "")
    assert cli.removed == [[3, 4]]
    assert importer.latest_import(tmp_path / "lib", tmp_path) is None
    record = importer.write_import_record(tmp_path, tmp_path / "lib", [5], ["C"])
    cli.remove_books = lambda *a: (False, "biblioteca aberta")
    assert importer.undo_import(record, cli) == (0, "biblioteca aberta")
    assert record.is_file()  # continua disponível para tentar de novo
