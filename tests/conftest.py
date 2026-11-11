"""Fábrica de PDFs de teste (gerados na hora; nada de arquivos reais)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf2calibre.models import Options  # noqa: E402


def _make_pdf(path: Path, title: str | None = None, author: str | None = None,
              text: str = "conteudo") -> Path:
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path))
    if title is not None:
        pdf.setTitle(title)
    if author is not None:
        pdf.setAuthor(author)
    pdf.drawString(72, 720, text)
    pdf.save()
    return path


@pytest.fixture
def make_pdf():
    return _make_pdf


@pytest.fixture
def options() -> Options:
    return Options(workers=2)
