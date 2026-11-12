import json

from personal_library import settings
from personal_library.models import ImportOptions


def test_roundtrip(tmp_path):
    path = tmp_path / "cfg" / "settings.json"
    saved = settings.Settings(library="/l", cli_path="/c", destination="/d", last_sources=["/a"],
                              export_folder_per_book=False, export_opf=False,
                              export_cover=False, gallery_sort="title")
    saved.set_options(ImportOptions(tags=["x"], filename_pattern="@name - @vol"))
    assert settings.save_settings(saved, path)
    loaded = settings.load_settings(path)
    assert loaded == saved
    assert loaded.get_options().tags == ["x"]
    assert loaded.get_options().filename_pattern == "@name - @vol"


def test_tolerates_corrupt_or_wrong_types(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{não é json")
    assert settings.load_settings(path) == settings.Settings()
    path.write_text(json.dumps({"destination": 5, "export_opf": "sim", "options": {"xyz": 1},
                                "last_sources": ["a", 3]}))
    loaded = settings.load_settings(path)
    assert loaded.destination == "" and loaded.export_opf is True
    assert loaded.last_sources == ["a"]
    path.write_text("[1, 2]")
    assert settings.load_settings(path) == settings.Settings()


def test_missing_file_gives_defaults(tmp_path):
    assert settings.load_settings(tmp_path / "nada.json") == settings.Settings()


def test_import_options_ignore_unknown_keys_and_wrong_types():
    options = ImportOptions.from_dict({"filename_pattern": 5, "tags": "x", "recursive": False,
                                       "mode": "mover"})
    assert options.filename_pattern == "" and options.tags == [] and options.recursive is False
