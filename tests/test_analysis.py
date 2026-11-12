import io
import threading

from pypdf import PdfReader, PdfWriter

from personal_library import analysis, files, pdf_reader
from personal_library.models import ImportOptions, Status


def test_junk_detection():
    assert pdf_reader.is_junk_title("Microsoft Word - trabalho.docx")
    assert pdf_reader.is_junk_title("untitled")
    assert pdf_reader.is_junk_title("relatorio.indd")
    assert pdf_reader.is_junk_title("123")
    assert not pdf_reader.is_junk_title("Dom Casmurro")
    assert pdf_reader.is_junk_author("admin")
    assert pdf_reader.is_junk_author("Acrobat PDFMaker")
    assert not pdf_reader.is_junk_author("Machado de Assis")


def test_sha256_is_stable(tmp_path):
    file = tmp_path / "a.bin"
    file.write_bytes(b"abc")
    assert files.sha256_file(file) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_reads_title_author_and_pages(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", title="Dom Casmurro", author="Machado de Assis")
    info = pdf_reader.read_pdf_info(pdf)
    assert info.title == "Dom Casmurro"
    assert info.author == "Machado de Assis"
    assert info.pages == 1
    assert info.readable and not info.locked


def test_corrupted_pdf_is_reported_not_raised(tmp_path):
    bad = tmp_path / "ruim.pdf"
    bad.write_bytes(b"%PDF-1.4\nisto nao e um pdf de verdade")
    info = pdf_reader.read_pdf_info(bad)
    assert info.readable is False
    assert info.error


def test_locked_pdf_needs_password(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.encrypt("segredo")
    path = tmp_path / "trancado.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    info = pdf_reader.read_pdf_info(path)
    assert info.encrypted and info.locked


def test_build_entry_prefers_pdf_metadata(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "qualquer nome.pdf", title="Dom Casmurro", author="Assis, Machado")
    entry = analysis.build_entry(pdf, ImportOptions())
    assert entry.title == "Dom Casmurro"
    assert entry.author == "Machado Assis"
    assert entry.title_origin == "pdf"
    assert entry.status is Status.READY
    assert len(entry.sha256) == 64


def test_build_entry_falls_back_to_filename(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Clarice Lispector - A Hora da Estrela.pdf",
                   title="Microsoft Word - x.docx", author="admin")
    entry = analysis.build_entry(pdf, ImportOptions())
    assert entry.title == "A Hora da Estrela"
    assert entry.author == "Clarice Lispector"
    assert entry.title_origin == "arquivo"


def test_build_entry_can_ignore_pdf_metadata(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Autor Teste - Titulo Teste.pdf", title="Outro", author="Alguem")
    entry = analysis.build_entry(pdf, ImportOptions(prefer_pdf_metadata=False))
    assert (entry.title, entry.author) == ("Titulo Teste", "Autor Teste")


def test_build_entry_unknown_author_is_warning(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "apostila de fisica.pdf")
    entry = analysis.build_entry(pdf, ImportOptions())
    assert entry.author == "Unknown"
    assert entry.status is Status.WARNING
    assert entry.usable


def test_build_entry_rejects_empty_and_non_pdf(tmp_path):
    empty = tmp_path / "vazio.pdf"
    empty.write_bytes(b"")
    fake = tmp_path / "texto.pdf"
    fake.write_text("só texto")
    assert analysis.build_entry(empty, ImportOptions()).status is Status.ERROR
    assert analysis.build_entry(fake, ImportOptions()).status is Status.ERROR


def test_build_entry_corrupted_is_warning_but_unselected(tmp_path):
    bad = tmp_path / "Autor Um - Quebrado.pdf"
    bad.write_bytes(b"%PDF-1.4\nlixo")
    entry = analysis.build_entry(bad, ImportOptions())
    assert entry.status is Status.WARNING
    assert entry.selected is False
    assert not entry.usable


def test_reader_roundtrip_matches_pypdf(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", title="T", author="A B")
    reader = PdfReader(io.BytesIO(pdf.read_bytes()))
    assert len(reader.pages) == 1


def test_volume_in_file_name_beats_pdf_title(make_pdf, tmp_path):
    """O PDF diz só 'One Punch Man'; o volume do nome do arquivo não pode se perder."""
    pdf = make_pdf(tmp_path / "One Punch Man - Vol 18.pdf", title="One Punch Man", author="ONE")
    entry = analysis.build_entry(pdf, ImportOptions())
    assert entry.title == "One Punch Man"
    assert (entry.series, entry.series_index) == ("One Punch Man", 18)
    assert entry.author == "ONE"  # o PDF completa o autor que o nome não trazia


def test_user_pattern_is_used_and_wins(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Naruto - 03 - Masashi Kishimoto.pdf", title="Outro Título",
                   author="Outro Autor")
    entry = analysis.build_entry(pdf, ImportOptions(filename_pattern="@name - @vol - @auth"))
    assert (entry.title, entry.author) == ("Naruto", "Masashi Kishimoto")
    assert entry.series_index == 3
    assert entry.status is Status.READY


def test_file_outside_the_pattern_is_flagged(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Machado de Assis - Dom Casmurro.pdf")  # sem volume
    entry = analysis.build_entry(pdf, ImportOptions(filename_pattern="@name - @vol - @auth"))
    assert entry.status is Status.WARNING
    assert any("fora do padrão" in note for note in entry.notes)
    assert entry.title == "Dom Casmurro"  # caiu no modo automático


def test_invalid_pattern_falls_back_to_automatic(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Machado de Assis - Dom Casmurro.pdf")
    entry = analysis.build_entry(pdf, ImportOptions(filename_pattern="@vol - @auth"))
    assert entry.title == "Dom Casmurro"


def test_fixed_values_override_pdf_and_file_name(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "One Punch Man - Vol 18 - Fulano.pdf", title="OPM",
                   author="Outro Autor")
    options = ImportOptions(filename_pattern="@name - @vol - @auth=ONE; @tags=mangá; "
                                       "@publisher=Panini; @lang=pt")
    entry = analysis.build_entry(pdf, options)
    assert (entry.title, entry.author, entry.author_origin) == ("One Punch Man", "ONE", "fixo")
    assert (entry.publisher, entry.language, entry.tags) == ("Panini", "pt", ["mangá"])
    assert entry.status is Status.READY


def test_fixed_author_avoids_unknown(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "apostila de fisica.pdf")
    entry = analysis.build_entry(pdf, ImportOptions(filename_pattern="@auth=Prof. Silva"))
    assert entry.author == "Prof. Silva" and entry.status is Status.READY


def test_volume_in_author_or_title_is_flagged(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "One Punch Man - Vol 01.pdf")
    entry = analysis.build_entry(pdf, ImportOptions(filename_pattern="@name - @auth"))
    assert (entry.title, entry.author) == ("One Punch Man", "Vol 01")
    assert entry.status is Status.WARNING
    assert any("parece um volume" in note for note in entry.notes)


# ---------------------------------------------------------------- arquivos e duplicados

def _scan(root, options, **kwargs):
    files = analysis.find_pdfs([root], options.recursive, **kwargs)
    return analysis.build_entries(files, options)


def test_find_pdfs_recursive_and_filters(make_pdf, tmp_path):
    make_pdf(tmp_path / "a.pdf")
    make_pdf(tmp_path / "sub" / "b.PDF")
    make_pdf(tmp_path / ".oculta" / "c.pdf")
    (tmp_path / "nota.txt").write_text("x")
    (tmp_path / "._lixo.pdf").write_bytes(b"x")
    names = [p.name for p in analysis.find_pdfs([tmp_path])]
    assert names == ["a.pdf", "b.PDF"]


def test_find_pdfs_not_recursive_and_dedup(make_pdf, tmp_path):
    first = make_pdf(tmp_path / "a.pdf")
    make_pdf(tmp_path / "sub" / "b.pdf")
    found = analysis.find_pdfs([tmp_path, first], recursive=False)
    assert [p.name for p in found] == ["a.pdf"]


def test_find_pdfs_excludes_destination(make_pdf, tmp_path):
    make_pdf(tmp_path / "a.pdf")
    make_pdf(tmp_path / "biblioteca" / "b.pdf")
    found = analysis.find_pdfs([tmp_path], exclude=tmp_path / "biblioteca")
    assert [p.name for p in found] == ["a.pdf"]


def test_find_pdfs_natural_order(make_pdf, tmp_path):
    for name in ("livro10.pdf", "livro2.pdf", "livro1.pdf"):
        make_pdf(tmp_path / name)
    assert [p.name for p in analysis.find_pdfs([tmp_path])] == [
        "livro1.pdf", "livro2.pdf", "livro10.pdf"]


def test_build_entries_keeps_order_and_reports_progress(make_pdf, tmp_path, options):
    for index in range(5):
        make_pdf(tmp_path / f"Autor {index} - Livro {index}.pdf", text=f"t{index}")
    seen = []
    files = analysis.find_pdfs([tmp_path])
    entries = analysis.build_entries(files, options, lambda d, t, m: seen.append((d, t)))
    assert [e.source for e in entries] == files
    assert seen[-1] == (5, 5)


def test_build_entries_cancel(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "a.pdf")
    cancel = threading.Event()
    cancel.set()
    assert analysis.build_entries(analysis.find_pdfs([tmp_path]), options, cancel=cancel) == []


def test_identical_files_are_duplicates(make_pdf, tmp_path, options):
    original = make_pdf(tmp_path / "Autor Um - Livro.pdf", text="igual")
    (tmp_path / "Autor Um - Livro copia.pdf").write_bytes(original.read_bytes())
    entries = _scan(tmp_path, options)
    assert analysis.mark_duplicates(entries, options) == 1
    assert [e.status for e in entries] == [Status.READY, Status.DUPLICATE]
    assert entries[1].selected is False


def test_duplicate_keeps_the_copy_with_better_metadata(make_pdf, tmp_path, options):
    # "Livros/..." vem antes na ordem das pastas, mas não tem autor
    original = make_pdf(tmp_path / "Machado de Assis - Dom Casmurro.pdf", text="igual")
    (tmp_path / "Livros").mkdir()
    (tmp_path / "Livros" / "Dom Casmurro - copia.pdf").write_bytes(original.read_bytes())
    entries = _scan(tmp_path, options)
    assert entries[0].source.parent.name == "Livros"  # confirma a ordem do cenário
    analysis.mark_duplicates(entries, options)
    kept = [e for e in entries if e.usable]
    assert [e.source.name for e in kept] == ["Machado de Assis - Dom Casmurro.pdf"]
    assert entries[0].status is Status.DUPLICATE
    assert "idêntico a Machado de Assis - Dom Casmurro.pdf" in entries[0].notes


def test_duplicates_only_noted_when_not_skipping(make_pdf, tmp_path):
    options = ImportOptions(workers=1, skip_duplicates=False)
    original = make_pdf(tmp_path / "Autor Um - Livro.pdf", text="igual")
    (tmp_path / "Autor Um - Livro copia.pdf").write_bytes(original.read_bytes())
    entries = _scan(tmp_path, options)
    analysis.mark_duplicates(entries, options)
    assert all(e.usable for e in entries)
    assert any("idêntico" in n for n in entries[1].notes)


def test_same_title_author_different_file_warns(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "Autor Um - Livro.pdf", text="versao 1")
    make_pdf(tmp_path / "Autor Um - Livro (2019).pdf", text="versao 2")
    entries = _scan(tmp_path, options)
    analysis.mark_duplicates(entries, options)
    assert entries[1].status is Status.WARNING
    assert entries[1].usable


def test_summarize_counts_by_status(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "Autor Um - Livro.pdf")
    (tmp_path / "vazio.pdf").write_bytes(b"")
    counts = analysis.summarize(_scan(tmp_path, options))
    assert counts[Status.READY] == 1
    assert counts[Status.ERROR] == 1


def test_volumes_with_same_title_are_not_duplicates(tmp_path, make_pdf):
    src = tmp_path / "opm"
    for number in (1, 2, 18):
        make_pdf(src / f"One Punch Man - Vol {number}.pdf", text=str(number))
    options = ImportOptions(workers=1, filename_pattern="@name - @vol; @auth=ONE")
    entries = analysis.build_entries(analysis.find_pdfs([src]), options)
    analysis.mark_duplicates(entries, options)
    assert {e.title for e in entries} == {"One Punch Man"}
    assert all(e.status is Status.READY for e in entries)  # volumes diferentes
    assert not any("mesmo título" in note for e in entries for note in e.notes)


def test_book_key_compares_volume_and_ignores_case_and_accents():
    key = analysis.book_key
    assert key("One Punch Man", ["ONE"], "One Punch Man", 1) != \
        key("One Punch Man", ["ONE"], "One Punch Man", 2)
    assert key("O Cortiço", ["Aluísio Azevedo"]) == key("o cortico", ["ALUISIO AZEVEDO"])
    assert key("Dom Casmurro", ["A", "B"]) == key("Dom Casmurro", ["B", "A"])
