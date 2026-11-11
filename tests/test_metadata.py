import io

from pypdf import PdfReader, PdfWriter

from pdf2calibre import metadata
from pdf2calibre.models import Options, Status


def test_junk_detection():
    assert metadata.is_junk_title("Microsoft Word - trabalho.docx")
    assert metadata.is_junk_title("untitled")
    assert metadata.is_junk_title("relatorio.indd")
    assert metadata.is_junk_title("123")
    assert not metadata.is_junk_title("Dom Casmurro")
    assert metadata.is_junk_author("admin")
    assert metadata.is_junk_author("Acrobat PDFMaker")
    assert not metadata.is_junk_author("Machado de Assis")


def test_sha256_is_stable(tmp_path):
    file = tmp_path / "a.bin"
    file.write_bytes(b"abc")
    assert metadata.sha256_file(file) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_reads_title_author_and_pages(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", title="Dom Casmurro", author="Machado de Assis")
    info = metadata.read_pdf_info(pdf)
    assert info.title == "Dom Casmurro"
    assert info.author == "Machado de Assis"
    assert info.pages == 1
    assert info.readable and not info.locked


def test_corrupted_pdf_is_reported_not_raised(tmp_path):
    bad = tmp_path / "ruim.pdf"
    bad.write_bytes(b"%PDF-1.4\nisto nao e um pdf de verdade")
    info = metadata.read_pdf_info(bad)
    assert info.readable is False
    assert info.error


def test_locked_pdf_needs_password(tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(200, 200)
    writer.encrypt("segredo")
    path = tmp_path / "trancado.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    info = metadata.read_pdf_info(path)
    assert info.encrypted and info.locked


def test_build_entry_prefers_pdf_metadata(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "qualquer nome.pdf", title="Dom Casmurro", author="Assis, Machado")
    entry = metadata.build_entry(pdf, Options())
    assert entry.title == "Dom Casmurro"
    assert entry.author == "Machado Assis"
    assert entry.title_origin == "pdf"
    assert entry.status is Status.READY
    assert len(entry.sha256) == 64


def test_build_entry_falls_back_to_filename(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Clarice Lispector - A Hora da Estrela.pdf",
                   title="Microsoft Word - x.docx", author="admin")
    entry = metadata.build_entry(pdf, Options())
    assert entry.title == "A Hora da Estrela"
    assert entry.author == "Clarice Lispector"
    assert entry.title_origin == "arquivo"


def test_build_entry_can_ignore_pdf_metadata(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Autor Teste - Titulo Teste.pdf", title="Outro", author="Alguem")
    entry = metadata.build_entry(pdf, Options(prefer_pdf_metadata=False))
    assert (entry.title, entry.author) == ("Titulo Teste", "Autor Teste")


def test_build_entry_unknown_author_is_warning(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "apostila de fisica.pdf")
    entry = metadata.build_entry(pdf, Options())
    assert entry.author == "Unknown"
    assert entry.status is Status.WARNING
    assert entry.usable


def test_build_entry_rejects_empty_and_non_pdf(tmp_path):
    empty = tmp_path / "vazio.pdf"
    empty.write_bytes(b"")
    fake = tmp_path / "texto.pdf"
    fake.write_text("só texto")
    assert metadata.build_entry(empty, Options()).status is Status.ERROR
    assert metadata.build_entry(fake, Options()).status is Status.ERROR


def test_build_entry_corrupted_is_warning_but_unselected(tmp_path):
    bad = tmp_path / "Autor Um - Quebrado.pdf"
    bad.write_bytes(b"%PDF-1.4\nlixo")
    entry = metadata.build_entry(bad, Options())
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
    entry = metadata.build_entry(pdf, Options())
    assert entry.title == "One Punch Man"
    assert (entry.series, entry.series_index) == ("One Punch Man", 18)
    assert entry.author == "ONE"  # o PDF completa o autor que o nome não trazia


def test_user_pattern_is_used_and_wins(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Naruto - 03 - Masashi Kishimoto.pdf", title="Outro Título",
                   author="Outro Autor")
    entry = metadata.build_entry(pdf, Options(filename_pattern="@name - @vol - @auth"))
    assert (entry.title, entry.author) == ("Naruto", "Masashi Kishimoto")
    assert entry.series_index == 3
    assert entry.status is Status.READY


def test_file_outside_the_pattern_is_flagged(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Machado de Assis - Dom Casmurro.pdf")  # sem volume
    entry = metadata.build_entry(pdf, Options(filename_pattern="@name - @vol - @auth"))
    assert entry.status is Status.WARNING
    assert any("fora do padrão" in note for note in entry.notes)
    assert entry.title == "Dom Casmurro"  # caiu no modo automático


def test_invalid_pattern_falls_back_to_automatic(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "Machado de Assis - Dom Casmurro.pdf")
    entry = metadata.build_entry(pdf, Options(filename_pattern="@vol - @auth"))
    assert entry.title == "Dom Casmurro"


def test_fixed_values_override_pdf_and_file_name(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "One Punch Man - Vol 18 - Fulano.pdf", title="OPM",
                   author="Outro Autor")
    options = Options(filename_pattern="@name - @vol - @auth=ONE; @tags=mangá; "
                                       "@publisher=Panini; @lang=pt")
    entry = metadata.build_entry(pdf, options)
    assert (entry.title, entry.author, entry.author_origin) == ("One Punch Man", "ONE", "fixo")
    assert (entry.publisher, entry.language, entry.tags) == ("Panini", "pt", ["mangá"])
    assert entry.status is Status.READY


def test_fixed_author_avoids_unknown(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "apostila de fisica.pdf")
    entry = metadata.build_entry(pdf, Options(filename_pattern="@auth=Prof. Silva"))
    assert entry.author == "Prof. Silva" and entry.status is Status.READY


def test_volume_in_author_or_title_is_flagged(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "One Punch Man - Vol 01.pdf")
    entry = metadata.build_entry(pdf, Options(filename_pattern="@name - @auth"))
    assert (entry.title, entry.author) == ("One Punch Man", "Vol 01")
    assert entry.status is Status.WARNING
    assert any("parece um volume" in note for note in entry.notes)
