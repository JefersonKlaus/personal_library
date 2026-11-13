"""Pages of a PDF as images, one at a time (the reader of the gallery)."""
from __future__ import annotations

import io
import threading
from collections import OrderedDict
from pathlib import Path

# PDFium error codes (pypdfium2.raw.FPDF_ERR_*).
_ERR_PASSWORD = 4


class PdfOpenError(Exception):
    """The PDF cannot be read in the app (message ready to be shown)."""


class PdfPages:
    """An open PDF that renders one page at a time, as JPEG bytes.

    PDFium is not thread-safe, so every call goes through one lock: the reader renders in
    a background thread (the window does not freeze) and never two pages at once. The
    last pages rendered stay in memory, so going back and forth is instant."""

    def __init__(self, path: Path | str, size: int = 1800, cache_size: int = 8) -> None:
        try:
            import pypdfium2 as pdfium
            import PIL  # noqa: F401  (pypdfium2 uses Pillow to make the image)
        except ImportError:
            raise PdfOpenError("para ler no app, instale o pypdfium2 e o Pillow "
                               "(pip install -r requirements.txt).") from None
        self.path = Path(path)
        self.size = size  # longest side of the rendered page, in pixels
        self._lock = threading.Lock()
        self._cache: OrderedDict[int, bytes] = OrderedDict()
        self._cache_size = cache_size
        self._closed = False
        try:
            self._document = pdfium.PdfDocument(str(self.path))
        except pdfium.PdfiumError as exc:
            if getattr(exc, "err_code", None) == _ERR_PASSWORD:
                raise PdfOpenError("o PDF é protegido por senha.") from None
            raise PdfOpenError("o arquivo está danificado ou não é um PDF válido.") from None
        except OSError as exc:
            raise PdfOpenError(f"não foi possível ler o arquivo ({exc}).") from None
        self.page_count = len(self._document)
        if not self.page_count:
            self.close()
            raise PdfOpenError("o PDF não tem páginas.")

    def is_ready(self, index: int) -> bool:
        """Already rendered (showing it needs no wait)."""
        return index in self._cache

    def render(self, index: int) -> bytes:
        """JPEG of the page (`index` from 0). Raises IndexError outside the document."""
        if not 0 <= index < self.page_count:
            raise IndexError(index)
        with self._lock:
            if self._closed:  # e.g. a prefetch that started after the reader closed
                raise RuntimeError("the PDF is closed")
            if index in self._cache:
                self._cache.move_to_end(index)
                return self._cache[index]
            page = self._document[index]
            try:
                width, height = page.get_size()
                scale = min(4.0, self.size / max(width, height, 1))
                image = page.render(scale=scale).to_pil().convert("RGB")
            finally:
                page.close()
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=90)
            data = buffer.getvalue()
            self._cache[index] = data
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
            return data

    def close(self) -> None:
        """Frees the document; waits for a render in progress. Safe to call twice."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._cache.clear()
            self._document.close()


def check_pdf(path: Path | str) -> int:
    """Opens and closes the PDF: its page count, or PdfOpenError (message ready)."""
    pages = PdfPages(path)
    count = pages.page_count
    pages.close()
    return count
