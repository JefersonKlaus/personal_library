"""Cover thumbnails for the gallery (cached on disk)."""
from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

from .database import LibraryBook

logger = logging.getLogger(__name__)

THUMB_SIZE = (200, 300)  # 2:3, the aspect ratio of a book cover


def thumbnail(book: LibraryBook, library: Path, cache_dir: Path | None,
              size: tuple[int, int] = THUMB_SIZE) -> bytes | None:
    """Small JPEG of the cover (cached on disk). Never raises.

    Without Pillow it returns the original cover, which works, just heavier.
    """
    cover = book.cover_path(library)
    if cover is None:
        return None
    try:
        stat = cover.stat()
        key = f"{Path(library).resolve()}|{book.id}|{stat.st_mtime_ns}|{stat.st_size}|{size}"
        cached = None
        if cache_dir is not None:
            cached = Path(cache_dir) / f"{hashlib.sha1(key.encode()).hexdigest()}.jpg"
            if cached.is_file():
                return cached.read_bytes()
        try:
            from PIL import Image
        except ImportError:
            return cover.read_bytes()
        with Image.open(cover) as image:
            image = image.convert("RGB")
            image.thumbnail(size)
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=82)
        data = buffer.getvalue()
        if cached is not None:
            cached.parent.mkdir(parents=True, exist_ok=True)
            temp = cached.with_suffix(".part")
            temp.write_bytes(data)
            temp.replace(cached)
        return data
    except Exception as exc:  # corrupt cover, no permission, disk full...
        logger.warning("Unreadable cover of %s: %s", book.title, exc)
        return None
