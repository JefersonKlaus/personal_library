"""Pages of a PDF rendered one at a time (the reader of the gallery)."""
import io
from concurrent.futures import ThreadPoolExecutor

import pytest

from helpers import make_pdf
from src.pdf.pdf_pages import PdfOpenError, PdfPages


pytest.importorskip("pypdfium2")
Image = pytest.importorskip("PIL.Image")


def _size(data):
    return Image.open(io.BytesIO(data)).size


def test_pages_are_jpegs_with_the_longest_side_at_the_given_size(tmp_path):
    pages = PdfPages(make_pdf(tmp_path / "a.pdf", pages=3), size=1000)
    assert pages.page_count == 3
    data = pages.render(0)
    assert data[:3] == b"\xff\xd8\xff"
    width, height = _size(data)
    assert height == pytest.approx(1000, abs=2) and width < height  # A4 portrait
    landscape = PdfPages(make_pdf(tmp_path / "b.pdf", pages=3, landscape=True), size=1000)
    width, height = _size(landscape.render(0))
    assert width == pytest.approx(1000, abs=2) and height < width
    pages.close()
    landscape.close()


def test_rendered_pages_are_kept_for_going_back_and_forth(tmp_path):
    pages = PdfPages(make_pdf(tmp_path / "a.pdf", pages=4), cache_size=2)
    assert not pages.is_ready(0)
    first = pages.render(0)
    assert pages.is_ready(0) and pages.render(0) is first  # no second render
    pages.render(1)
    pages.render(2)  # only the last 2 are kept
    assert not pages.is_ready(0) and pages.is_ready(1) and pages.is_ready(2)
    pages.close()


def test_pages_outside_the_document(tmp_path):
    pages = PdfPages(make_pdf(tmp_path / "a.pdf", pages=3))
    for index in (-1, 3):
        with pytest.raises(IndexError):
            pages.render(index)
    pages.close()


def test_files_that_cannot_be_read_in_the_app(tmp_path):
    from pypdf import PdfReader, PdfWriter

    plain = make_pdf(tmp_path / "plain.pdf", pages=3)
    writer = PdfWriter()
    for page in PdfReader(plain).pages:
        writer.add_page(page)
    writer.encrypt("segredo")
    locked = tmp_path / "locked.pdf"
    with locked.open("wb") as handle:
        writer.write(handle)
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4 nothing else")
    with pytest.raises(PdfOpenError, match="protegido por senha"):
        PdfPages(locked)
    with pytest.raises(PdfOpenError, match="danificado"):
        PdfPages(broken)
    with pytest.raises(PdfOpenError):
        PdfPages(tmp_path / "missing.pdf")


def test_close_twice_and_render_after_close(tmp_path):
    pages = PdfPages(make_pdf(tmp_path / "a.pdf", pages=3))
    pages.render(0)
    pages.close()
    pages.close()
    with pytest.raises(RuntimeError):  # a prefetch that started too late: no crash
        pages.render(1)


def test_one_render_at_a_time(tmp_path):
    """PDFium is not thread-safe: a render waits while another one holds the lock
    (a crash from two at once is too random to catch by just trying)."""
    pages = PdfPages(make_pdf(tmp_path / "a.pdf", pages=3), cache_size=0)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with pages._lock:  # as if another thread were rendering
            waiting = pool.submit(pages.render, 0)
            with pytest.raises(TimeoutError):
                waiting.result(timeout=0.3)
        assert waiting.result(timeout=10)[:3] == b"\xff\xd8\xff"
    pages.close()


def test_renders_from_several_threads_at_once(tmp_path):
    pages = PdfPages(make_pdf(tmp_path / "a.pdf", pages=6), cache_size=0)
    alone = [pages.render(index) for index in range(6)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        together = list(pool.map(pages.render, [0, 1, 2, 3, 4, 5] * 3))
    assert together == alone * 3
    pages.close()
