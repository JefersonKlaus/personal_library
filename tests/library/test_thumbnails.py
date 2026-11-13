"""Cover thumbnails for the gallery."""
import sys

import pytest

from src.library import database, thumbnails


def _by_title(books):
    return {book.title: book for book in books}


def test_thumbnail_is_small_and_cached(make_library, tmp_path):
    pytest.importorskip("PIL")
    root = make_library(tmp_path / "lib")
    book = _by_title(database.load_library(root))["Dom Casmurro"]
    cache = tmp_path / "cache"
    first = thumbnails.thumbnail(book, root, cache)
    assert first[:3] == b"\xff\xd8\xff"
    assert len(list(cache.glob("*.jpg"))) == 1
    from PIL import Image
    import io
    assert max(Image.open(io.BytesIO(first)).size) <= max(thumbnails.THUMB_SIZE)
    assert thumbnails.thumbnail(book, root, cache) == first  # from the cache


def test_thumbnail_never_raises(make_library, tmp_path, monkeypatch):
    root = make_library(tmp_path / "lib")
    book = _by_title(database.load_library(root))["Dom Casmurro"]
    book.cover_path(root).write_bytes(b"capa corrompida")
    assert thumbnails.thumbnail(book, root, tmp_path / "cache") is None
    monkeypatch.setitem(sys.modules, "PIL", None)  # without Pillow: the original cover
    assert thumbnails.thumbnail(book, root, None) == b"capa corrompida"
