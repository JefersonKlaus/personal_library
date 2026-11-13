"""Volumes in the file name."""
from src.parsing import volumes


def test_looks_like_volume():
    assert volumes.looks_like_volume("Vol 01") and volumes.looks_like_volume("v03")
    assert not volumes.looks_like_volume("ONE") and not volumes.looks_like_volume("1984")
