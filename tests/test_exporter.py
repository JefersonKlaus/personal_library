import xml.etree.ElementTree as ET

import pytest

from src.exporting import exporter
from src.core.files import FileOperationError, undo_manifest
from src.library import database as lib
from src.library.manager import OPF_META_PREFIX, OPF_TRUSTED_SCHEME
from src.core.models import Status

NS = {"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf"}
OPF = "{http://www.idpf.org/2007/opf}"


def _books(make_library, tmp_path):
    root = make_library(tmp_path / "Biblioteca")
    return root, {book.title: book for book in lib.load_library(root)}


# ---------------------------------------------------------------- Exportar

def test_export_creates_folder_per_book_layout(make_library, tmp_path):
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
    assert ids[OPF_TRUSTED_SCHEME] and ids["ISBN"] == "9788535910667"
    assert opf.find(".//dc:publisher", NS).text == "Garnier"
    assert opf.find(".//dc:date", NS).text == "1899-06-15T12:00:00+00:00"
    assert [n.text for n in opf.findall(".//dc:language", NS)] == ["por", "eng"]
    assert sorted(n.text for n in opf.findall(".//dc:subject", NS)) == ["Brasil", "Romance"]
    assert "<b>Bento</b>" in opf.find(".//dc:description", NS).text
    metas = {m.attrib["name"]: m.attrib["content"] for m in opf.findall(f".//{OPF}meta")}
    assert metas[f"{OPF_META_PREFIX}series"] == "Clássicos"
    assert metas[f"{OPF_META_PREFIX}series_index"] == "1"
    assert opf.find(f".//{OPF}reference").attrib["href"] == "cover.jpg"
    fisica = ET.parse(dest / "Ana Lima" / "Física Básica"
                      / "Física Básica - Ana Lima & Rui Dias.opf").getroot()
    creators = fisica.findall(".//dc:creator", NS)
    assert [c.text for c in creators] == ["Ana Lima", "Rui Dias"]
    # Convenção da biblioteca: a ordenação do livro todo em cada autor.
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


def test_export_refuses_destination_inside_a_library(make_library, tmp_path):
    root, books = _books(make_library, tmp_path)
    with pytest.raises(FileOperationError, match="dentro de uma biblioteca"):
        exporter.export_books(list(books.values()), root, root / "sub", exporter.ExportOptions())


def test_export_undo_and_failure_cleanup(make_library, tmp_path, monkeypatch):
    root, books = _books(make_library, tmp_path)
    dest = tmp_path / "saida"
    report, _items = exporter.export_books([books["Dom Casmurro"]], root, dest,
                                           exporter.ExportOptions())
    assert undo_manifest(report.manifest).failed == 0
    assert not list(dest.rglob("*.pdf")) and not (dest / "Machado de Assis").exists()

    def broken(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(exporter, "render_opf", broken)
    report, items = exporter.export_books([books["Dom Casmurro"]], root, dest,
                                          exporter.ExportOptions())
    assert report.failed == 1 and items[0].status is Status.FAILED
    assert not (dest / "Machado de Assis").exists()  # nem pasta, nem .part, nem capa


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
