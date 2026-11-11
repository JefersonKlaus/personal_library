import json
import os
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from pdf2calibre import calibre, exporter, library_import, organizer, planner
from pdf2calibre import library as lib
from pdf2calibre.models import Options, Status

NS = {"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf"}
OPF = "{http://www.idpf.org/2007/opf}"


def _books(make_library, tmp_path):
    root = make_library(tmp_path / "Calibre Library")
    return root, {book.title: book for book in lib.load_library(root)}


# ---------------------------------------------------------------- Exportar

def test_export_creates_calibre_layout(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    dest = tmp_path / "saida"
    report, items = exporter.export_books(list(books.values()), root, dest,
                                          exporter.ExportOptions())
    assert (report.done, report.failed) == (4, 0)
    folder = dest / "Machado de Assis" / "Dom Casmurro"
    assert (folder / "Dom Casmurro - Machado de Assis.pdf").read_bytes() == b"%PDF-1.4 livro"
    assert (folder / "cover.jpg").is_file()
    assert not (dest / "J. R. R. Tolkien" / "The Hobbit" / "cover.jpg").exists()  # sem capa
    assert not list(dest.rglob("*.part"))
    assert report.manifest and report.manifest.is_file()


def test_exported_opf_has_all_library_metadata(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    dest = tmp_path / "saida"
    exporter.export_books([books["Dom Casmurro"], books["Física Básica"]], root, dest,
                          exporter.ExportOptions())
    opf = ET.parse(dest / "Machado de Assis" / "Dom Casmurro"
                   / "Dom Casmurro - Machado de Assis.opf").getroot()
    ids = {n.attrib.get(f"{OPF}scheme"): n.text for n in opf.findall(".//dc:identifier", NS)}
    assert ids["calibre"] and ids["ISBN"] == "9788535910667"
    assert opf.find(".//dc:publisher", NS).text == "Garnier"
    assert opf.find(".//dc:date", NS).text == "1899-06-15T12:00:00+00:00"
    assert [n.text for n in opf.findall(".//dc:language", NS)] == ["por", "eng"]
    assert sorted(n.text for n in opf.findall(".//dc:subject", NS)) == ["Brasil", "Romance"]
    assert "<b>Bento</b>" in opf.find(".//dc:description", NS).text
    metas = {m.attrib["name"]: m.attrib["content"] for m in opf.findall(f".//{OPF}meta")}
    assert metas["calibre:series"] == "Clássicos" and metas["calibre:series_index"] == "1"
    assert opf.find(f".//{OPF}reference").attrib["href"] == "cover.jpg"
    fisica = ET.parse(dest / "Ana Lima" / "Física Básica"
                      / "Física Básica - Ana Lima & Rui Dias.opf").getroot()
    creators = fisica.findall(".//dc:creator", NS)
    assert [c.text for c in creators] == ["Ana Lima", "Rui Dias"]
    # Convenção do Calibre: o author_sort do livro todo em cada criador.
    assert {c.attrib[f"{OPF}file-as"] for c in creators} == {"Lima, Ana & Dias, Rui"}


def test_flat_layout_and_options(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    dest = tmp_path / "saida"
    options = exporter.ExportOptions(folder_per_book=False, write_opf=False)
    exporter.export_books([books["Dom Casmurro"]], root, dest, options)
    assert sorted(p.name for p in dest.iterdir() if p.is_file()) == [
        "Dom Casmurro - Machado de Assis.jpg", "Dom Casmurro - Machado de Assis.pdf"]


def test_export_again_skips_and_different_file_gets_new_name(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    dest = tmp_path / "saida"
    dom = books["Dom Casmurro"]
    exporter.export_books([dom], root, dest, exporter.ExportOptions())
    report, items = exporter.export_books([dom], root, dest, exporter.ExportOptions())
    assert report.done == 0 and items[0].status is Status.EXISTS
    existing = dest / "Machado de Assis" / "Dom Casmurro" / "Dom Casmurro - Machado de Assis.pdf"
    existing.write_bytes(b"outro arquivo, tamanho diferente")
    report, items = exporter.export_books([dom], root, dest, exporter.ExportOptions())
    assert report.done == 1
    assert items[0].target.parent.name == "Dom Casmurro (2)"
    assert existing.read_bytes() == b"outro arquivo, tamanho diferente"  # nada sobrescrito


def test_dry_run_and_missing_file(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    books["O Cortiço"].main_file(root).unlink()
    dest = tmp_path / "saida"
    report, items = exporter.export_books(list(books.values()), root, dest,
                                          exporter.ExportOptions(dry_run=True))
    assert not dest.exists()
    status = {item.book.title: item.status for item in items}
    assert status["O Cortiço"] is Status.ERROR
    assert report.done == 3 and report.skipped == 1


def test_export_refuses_calibre_library(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    with pytest.raises(organizer.OrganizerError, match="biblioteca do Calibre"):
        exporter.export_books(list(books.values()), root, root / "sub", exporter.ExportOptions())


def test_export_undo_and_failure_cleanup(make_library, tmp_path, monkeypatch):
    root, books = _books(make_library, tmp_path)
    dest = tmp_path / "saida"
    report, _items = exporter.export_books([books["Dom Casmurro"]], root, dest,
                                           exporter.ExportOptions())
    assert organizer.undo(report.manifest).failed == 0
    assert not list(dest.rglob("*.pdf")) and not (dest / "Machado de Assis").exists()

    def broken(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(exporter, "render_opf", broken)
    report, items = exporter.export_books([books["Dom Casmurro"]], root, dest,
                                          exporter.ExportOptions())
    assert report.failed == 1 and items[0].status is Status.FAILED
    assert not (dest / "Machado de Assis").exists()  # nem pasta, nem .part, nem capa


# ---------------------------------------------------------------- Importar

def _entries(tmp_path, make_pdf):
    src = tmp_path / "src"
    make_pdf(src / "Autor Um - Livro Um.pdf", text="1")
    make_pdf(src / "Autor Dois - Livro Dois.pdf", text="2")
    make_pdf(src / "Autor Tres - Livro Tres.pdf", text="3")
    options = Options(workers=1)
    return planner.build_entries(planner.find_pdfs([src]), options), options


def test_import_stages_opf_and_records_ids(tmp_path, make_pdf, make_library, monkeypatch):
    root = make_library(tmp_path / "Calibre Library")
    entries, options = _entries(tmp_path, make_pdf)
    seen = []

    def fake_import(ready, library, opts, tool, progress=None, cancel=None):
        results = []
        for entry in ready:
            # o calibredb recebe o PDF já com o OPF de mesmo nome e a capa ao lado
            seen.append((entry.target_file.name, entry.target_file.with_suffix(".opf").is_file(),
                         (entry.target_file.parent / "cover.jpg").is_file()))
        results.append(calibre.ImportResult(ready[0], True, [21]))
        results.append(calibre.ImportResult(ready[1], False, message="já existe na biblioteca",
                                            duplicate=True))
        results.append(calibre.ImportResult(ready[2], False, message="banco travado"))
        return results

    monkeypatch.setattr(calibre, "import_entries", fake_import)
    records = tmp_path / "records"
    report = library_import.import_to_library(entries, root, options, Path("calibredb"),
                                              records_dir=records)
    assert [s[1:] for s in seen] == [(True, True)] * 3
    assert (report.added, report.existing, report.failed) == (1, 1, 1)
    assert [e.status for e in entries] == [Status.DONE, Status.EXISTS, Status.FAILED]
    assert all(e.target_file is None for e in entries)
    assert not any(Path(s[0]).exists() for s in seen)  # pasta temporária apagada
    record = library_import.latest_import(root, records)
    data = json.loads(record.read_text(encoding="utf-8"))
    assert data["ids"] == [21] and data["library"] == str(root.resolve())
    assert library_import.latest_import(tmp_path / "outra", records) is None


def test_undo_import_removes_ids(tmp_path, monkeypatch):
    record = library_import.write_import_record(tmp_path, tmp_path / "lib", [3, 4], ["A", "B"])
    calls = []
    monkeypatch.setattr(calibre, "remove_books",
                        lambda tool, library, ids: calls.append(ids) or (True, ""))
    assert library_import.undo_import(record, Path("calibredb")) == (2, "")
    assert calls == [[3, 4]]
    assert library_import.latest_import(tmp_path / "lib", tmp_path) is None
    record = library_import.write_import_record(tmp_path, tmp_path / "lib", [5], ["C"])
    monkeypatch.setattr(calibre, "remove_books", lambda *a: (False, "Calibre aberto"))
    assert library_import.undo_import(record, Path("calibredb")) == (0, "Calibre aberto")
    assert record.is_file()  # continua disponível para tentar de novo


def test_import_with_nothing_selected(tmp_path, make_pdf):
    entries, options = _entries(tmp_path, make_pdf)
    for entry in entries:
        entry.selected = False
    report = library_import.import_to_library(entries, tmp_path, options, Path("x"))
    assert report.total == 0 and report.record is None


@pytest.mark.skipif(os.name == "nt", reason="usa um script shell falso")
def test_remove_books_calls_calibredb(tmp_path):
    fake = tmp_path / "calibredb"
    log = tmp_path / "args.txt"
    fake.write_text(f"#!{sys.executable}\nimport sys\nopen({str(log)!r}, 'w').write("
                    "' '.join(sys.argv[1:]))\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    assert calibre.remove_books(fake, tmp_path, [1, 2]) == (True, "")
    assert log.read_text() == f"remove --with-library {tmp_path} 1,2"
    assert calibre.remove_books(tmp_path / "nao-existe", tmp_path, [1])[0] is False
    assert calibre.remove_books(fake, tmp_path, []) == (True, "")


def test_volumes_already_in_library_are_skipped(tmp_path, make_pdf, make_library, monkeypatch):
    root = make_library(tmp_path / "Calibre Library")
    # "Dom Casmurro" está na biblioteca como Clássicos [1]
    src = tmp_path / "src"
    make_pdf(src / "Dom Casmurro - 1.pdf", text="a")
    make_pdf(src / "Dom Casmurro - 2.pdf", text="b")
    options = Options(workers=1, filename_pattern="@name - @vol; @auth=Machado de Assis; "
                                                  "@series=Clássicos")
    entries = planner.build_entries(planner.find_pdfs([src]), options)
    sent = []
    monkeypatch.setattr(calibre, "import_entries", lambda ready, *a, **k: sent.extend(ready) or [
        calibre.ImportResult(entry, True, [50]) for entry in ready])
    report = library_import.import_to_library(entries, root, options, Path("calibredb"),
                                              records_dir=tmp_path / "rec")
    assert [e.series_index for e in sent] == [2]  # o volume 1 já existe
    assert (report.added, report.existing) == (1, 1)
    vol1 = next(e for e in entries if e.series_index == 1)
    assert vol1.status is Status.EXISTS and "mesmo título, autor e volume" in vol1.notes[-1]


def test_export_names_volumes_with_same_title(make_library, tmp_path):
    books = [lib.LibraryBook(id=n, title="One Punch Man", authors=["ONE"], series="One Punch Man",
                             series_index=float(n), formats={"PDF": f"f{n}"}, path=f"ONE/OPM ({n})")
             for n in (1, 2)]
    root = tmp_path / "lib"
    for book in books:
        folder = book.folder(root)
        folder.mkdir(parents=True)
        (folder / f"f{book.id}.pdf").write_bytes(b"%PDF " + bytes([book.id]))
    items = exporter.plan_export(books, root, tmp_path / "out", exporter.ExportOptions())
    assert [item.target.name for item in items] == [
        "One Punch Man - Vol. 1 - ONE.pdf", "One Punch Man - Vol. 2 - ONE.pdf"]
    assert items[0].target.parent.name == "One Punch Man - Vol. 1"


def test_normal_books_in_a_series_keep_their_names(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    items = exporter.plan_export([books["Dom Casmurro"], books["O Cortiço"]], root,
                                 tmp_path / "out", exporter.ExportOptions())
    assert [item.target.name for item in items] == [
        "Dom Casmurro - Machado de Assis.pdf", "O Cortiço - Aluísio Azevedo.pdf"]
