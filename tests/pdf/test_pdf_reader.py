"""Reading PDFs: metadata from inside the file, junk values, locked files."""
import io

from pypdf import PdfReader, PdfWriter

from src.pdf import pdf_reader


def test_junk_detection():
    assert pdf_reader.is_junk_title("Microsoft Word - trabalho.docx")
    assert pdf_reader.is_junk_title("untitled")
    assert pdf_reader.is_junk_title("relatorio.indd")
    assert pdf_reader.is_junk_title("123")
    assert not pdf_reader.is_junk_title("Dom Casmurro")
    assert pdf_reader.is_junk_author("admin")
    assert pdf_reader.is_junk_author("Acrobat PDFMaker")
    assert not pdf_reader.is_junk_author("Machado de Assis")


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


def test_reader_roundtrip_matches_pypdf(make_pdf, tmp_path):
    pdf = make_pdf(tmp_path / "x.pdf", title="T", author="A B")
    reader = PdfReader(io.BytesIO(pdf.read_bytes()))
    assert len(reader.pages) == 1
