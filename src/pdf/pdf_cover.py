"""Cover of the book: the first page of the PDF as a JPEG."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def render_cover(pdf_path: Path, out_path: Path, max_side: int = 1400) -> bool:
    """Renders the first page as a JPEG.

    Needs `pypdfium2` and `Pillow`. Without them (or if the PDF fails) it returns
    False and the book is left without a cover.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.info("pypdfium2 not installed; covers disabled")
        return False

    try:
        document = pdfium.PdfDocument(str(pdf_path))
        try:
            if len(document) == 0:
                return False
            page = document[0]
            width, height = page.get_size()
            scale = min(2.0, max_side / max(width, height))
            image = page.render(scale=scale).to_pil().convert("RGB")
            image.save(out_path, "JPEG", quality=85)
            page.close()
        finally:
            document.close()
        return True
    except Exception as exc:  # odd PDFs or Pillow missing
        logger.warning("Could not extract the cover of %s: %s", pdf_path, exc)
        out_path.unlink(missing_ok=True)
        return False
