"""Fixtures of the tests; the helpers they use are in helpers.py."""
from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest

from helpers import UI_MODULES, FakeFlet, FakePage, make_library_at, make_pdf as _make_pdf
from src.core.models import ImportOptions


@pytest.fixture
def make_pdf():
    return _make_pdf


@pytest.fixture
def make_library():
    return make_library_at


@pytest.fixture
def options() -> ImportOptions:
    return ImportOptions(workers=2)


@pytest.fixture
def ui(monkeypatch):
    """The interface modules loaded with the fake Flet."""
    from src.core.settings import Settings

    monkeypatch.setitem(sys.modules, "flet", FakeFlet("flet"))
    for name in UI_MODULES:
        monkeypatch.delitem(sys.modules, f"src.ui.{name}", raising=False)
    modules = {name: importlib.import_module(f"src.ui.{name}") for name in UI_MODULES}
    monkeypatch.setattr(modules["app"], "load_settings", lambda: Settings())
    monkeypatch.setattr(modules["app"], "save_settings", lambda _settings: True)
    monkeypatch.setattr(modules["library_picker"], "known_libraries", lambda *a: [])
    # Never a real reader window (a separate process) in the tests: recorded instead.
    opened_windows = []
    monkeypatch.setattr(modules["book_opener"], "open_window",
                        lambda *args: opened_windows.append(args))
    yield SimpleNamespace(**modules, opened_windows=opened_windows)
    for name in UI_MODULES:
        sys.modules.pop(f"src.ui.{name}", None)


@pytest.fixture
def app(ui, tmp_path):
    instance = ui.app.PersonalLibraryApp(FakePage())
    instance.gallery.thumb_cache = tmp_path / "thumbs"  # does not use the user folder
    instance.build()
    return instance


@pytest.fixture
def fake_cli(monkeypatch):
    """Swaps the library tool; `fake_cli.set(None)` simulates 'not installed'."""
    from src.library.cli import LibraryCli

    holder = SimpleNamespace(tool=SimpleNamespace(name="cli"))
    holder.set = lambda tool: setattr(holder, "tool", tool)
    monkeypatch.setattr(LibraryCli, "find", classmethod(lambda cls, custom=None: holder.tool))
    return holder
