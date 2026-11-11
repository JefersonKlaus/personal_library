"""Extração opcional da capa (primeira página) como JPEG."""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def extract_cover(pdf_path: Path, out_path: Path, max_side: int = 1400) -> bool:
    """Renderiza a primeira página em JPEG.

    Precisa de `pypdfium2` e `Pillow`. Sem eles (ou se o PDF falhar) devolve
    False e o Calibre simplesmente cria o livro sem capa.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        logger.info("pypdfium2 não instalado; capas desativadas")
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
    except Exception as exc:  # PDFs estranhos ou falta de Pillow
        logger.warning("Não foi possível extrair a capa de %s: %s", pdf_path, exc)
        out_path.unlink(missing_ok=True)
        return False
