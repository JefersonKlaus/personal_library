import json

from personal_library.library import location
from personal_library.library.manager import (CONFIG_DIR_ENV, CURRENT_LIBRARY_FILE,
                                              CURRENT_LIBRARY_KEY, DATABASE_FILE,
                                              DEFAULT_LIBRARY_NAME, RECENT_LIBRARIES_FILE,
                                              RECENT_LIBRARIES_KEY)


def _library(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / DATABASE_FILE).write_bytes(b"")
    return path


def test_is_library_and_root(tmp_path):
    assert not location.is_library(tmp_path) and not location.is_library("")
    _library(tmp_path)
    assert location.is_library(tmp_path)
    assert location.find_library_root(tmp_path / "Autor" / "Livro") == tmp_path.absolute()
    assert location.find_library_root(tmp_path.parent / "fora") is None


def test_find_library_in_folder_or_single_child(tmp_path):
    lib = _library(tmp_path / "Documentos" / DEFAULT_LIBRARY_NAME)
    assert location.find_library_in(lib) == lib
    assert location.find_library_in(tmp_path / "Documentos") == lib
    _library(tmp_path / "Documentos" / "Outra")
    assert location.find_library_in(tmp_path / "Documentos") is None  # ambíguo
    assert location.find_library_in(tmp_path / "nao-existe") is None


def test_new_library_path(tmp_path):
    assert location.new_library_path(tmp_path / "nova") == tmp_path / "nova"
    empty = tmp_path / "vazia"
    empty.mkdir()
    assert location.new_library_path(empty) == empty
    busy = tmp_path / "Documentos"
    busy.mkdir()
    (busy / "foto.jpg").write_bytes(b"x")
    assert location.new_library_path(busy) == busy / DEFAULT_LIBRARY_NAME
    (busy / DEFAULT_LIBRARY_NAME).mkdir()
    (busy / DEFAULT_LIBRARY_NAME / "x").write_bytes(b"x")
    assert location.new_library_path(busy) == busy / f"{DEFAULT_LIBRARY_NAME} 2"


def test_known_libraries_reads_the_manager_config(tmp_path, monkeypatch):
    monkeypatch.setattr(location.Path, "home", lambda: tmp_path / "home")
    config = tmp_path / "config"
    config.mkdir()
    current, often, rare = (_library(tmp_path / n) for n in ("atual", "muito", "pouco"))
    (config / CURRENT_LIBRARY_FILE).write_text(json.dumps({CURRENT_LIBRARY_KEY: str(current)}))
    (config / RECENT_LIBRARIES_FILE).write_text(json.dumps({RECENT_LIBRARIES_KEY: {
        str(rare): 1, str(tmp_path / "apagada"): 50, str(often): 9, str(current): 3}}))
    default = _library(tmp_path / "home" / DEFAULT_LIBRARY_NAME)
    assert location.known_libraries(config) == [current, often, rare, default]
    assert location.known_libraries(tmp_path / "sem-config") == [default]


def test_manager_config_dir_respects_override(monkeypatch, tmp_path):
    monkeypatch.setenv(CONFIG_DIR_ENV, str(tmp_path))
    assert location.manager_config_dir() == tmp_path
