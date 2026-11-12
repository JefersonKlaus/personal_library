import pytest

from src.pdf import pdf_cover


def test_render_cover_makes_jpeg(tmp_path, make_pdf):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    out = tmp_path / "cover.jpg"
    assert pdf_cover.render_cover(make_pdf(tmp_path / "x.pdf"), out) is True
    assert out.read_bytes()[:3] == b"\xff\xd8\xff"


def test_render_cover_fails_gracefully(tmp_path):
    bad = tmp_path / "ruim.pdf"
    bad.write_bytes(b"%PDF-1.4 lixo")
    out = tmp_path / "cover.jpg"
    assert pdf_cover.render_cover(bad, out) is False
    assert not out.exists()
