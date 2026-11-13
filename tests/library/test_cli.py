import os
import stat
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from src.core.models import BookEntry
from src.library import cli
from src.library.manager import CLI_NAME, LANGUAGE_ENV


POSIX_ONLY = pytest.mark.skipif(os.name == "nt", reason="usa um script shell falso")


def _entry(**kwargs) -> BookEntry:
    data = dict(source=Path("x.pdf"), title="A & B", author="Ana Lima & Rui Dias", language="pt")
    data.update(kwargs)
    return BookEntry(**data)


def _fake_tool(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\nimport os, sys, pathlib\n{body}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


@pytest.mark.parametrize("flavor", [PurePosixPath, PureWindowsPath])
def test_add_command_uses_equals_form_and_native_paths(flavor):
    """The paths go in the format of the system ('/lib' on Linux, '\\\\lib' on Windows)."""
    tool, library = flavor("/bin/tool"), flavor("/lib")
    book, cover = library / "x.pdf", library / "cover.jpg"
    command = cli.add_command(tool, library, book, _entry(title="-Perigo"), ["a", "b"], cover)
    assert command[:4] == [str(tool), "add", "--with-library", str(library)]
    assert "--title=-Perigo" in command and "--authors=Ana Lima & Rui Dias" in command
    assert "--tags=a,b" in command and f"--cover={cover}" in command
    assert "--duplicates" not in command
    assert command[-1] == str(book)


def test_add_command_series_and_duplicates():
    volume = _entry(title="One Punch Man", series="One Punch Man", series_index=2.0)
    command = cli.add_command(Path("t"), Path("l"), Path("x.pdf"), volume, [],
                              allow_duplicate=True)
    assert "--duplicates" in command
    assert "--series=One Punch Man" in command and "--series-index=2" in command
    plain = cli.add_command(Path("t"), Path("l"), Path("x.pdf"), _entry(), [])
    assert not any(arg.startswith(("--series", "--tags")) for arg in plain)


def test_parse_added_ids():
    assert cli.parse_added_ids("Added book ids: 12, 13") == [12, 13]
    assert cli.parse_added_ids("nada") == []


def test_find_cli_custom_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(cli, "INSTALL_DIRS", ())
    assert cli.find_cli() is None and cli.LibraryCli.find() is None
    fake = tmp_path / CLI_NAME
    fake.write_text("x")
    assert cli.find_cli(str(fake)) == fake
    assert cli.find_cli(str(tmp_path)) == fake  # installation folder


@POSIX_ONLY
def test_add_book_results(tmp_path):
    tool = cli.LibraryCli(_fake_tool(tmp_path / "tool", (
        "if any('Repetido' in a for a in sys.argv):\n"
        "    print('The following books were not added'); sys.exit(0)\n"
        "if any('Quebrado' in a for a in sys.argv):\n"
        "    print('Another program is running', file=sys.stderr); sys.exit(1)\n"
        "print('Added book ids: 7')\n")))
    book = tmp_path / "x.pdf"
    assert tool.add_book(tmp_path, book, _entry(title="Bom"), []) == cli.AddResult(True, [7])
    repeated = tool.add_book(tmp_path, book, _entry(title="Repetido"), [])
    assert repeated.duplicate and "já existe" in repeated.message
    broken = tool.add_book(tmp_path, book, _entry(title="Quebrado"), [])
    # library in use: clear explanation instead of the technical output of the tool
    assert not broken.ok and broken.message == cli.LIBRARY_IN_USE
    assert "outro programa" in broken.message and "running" not in broken.message
    missing = cli.LibraryCli(tmp_path / "nao-existe").add_book(tmp_path, book, _entry(), [])
    assert not missing.ok and "não foi possível" in missing.message


@POSIX_ONLY
def test_output_is_forced_to_english(tmp_path, monkeypatch):
    """With the program in Portuguese the answer would be 'IDs de livro adicionados'."""
    monkeypatch.setenv(LANGUAGE_ENV, "pt_BR")
    tool = cli.LibraryCli(_fake_tool(tmp_path / "tool", (
        f"if os.environ.get({LANGUAGE_ENV!r}) != 'en':\n"
        "    print('IDs de livro adicionados: 7'); sys.exit(0)\n"
        "print('Added book ids: 7')\n")))
    assert tool.add_book(tmp_path, tmp_path / "x.pdf", _entry(), []).book_ids == [7]


@POSIX_ONLY
def test_remove_books(tmp_path):
    log = tmp_path / "args.txt"
    tool = cli.LibraryCli(_fake_tool(tmp_path / "tool",
                                     f"open({str(log)!r}, 'w').write(' '.join(sys.argv[1:]))\n"))
    assert tool.remove_books(tmp_path, [1, 2]) == (True, "")
    assert log.read_text() == f"remove --with-library {tmp_path} 1,2"
    assert tool.remove_books(tmp_path, []) == (True, "")
    assert cli.LibraryCli(tmp_path / "nao-existe").remove_books(tmp_path, [1])[0] is False


@POSIX_ONLY
def test_create_library(tmp_path):
    from src.library.location import is_library
    from src.library.manager import DATABASE_FILE

    tool = cli.LibraryCli(_fake_tool(tmp_path / "tool", (
        "lib = pathlib.Path(sys.argv[sys.argv.index('--with-library') + 1])\n"
        f"(lib / {DATABASE_FILE!r}).write_bytes(b'')\n")))
    target = tmp_path / "nova" / "Biblioteca"
    assert tool.create_library(target) == (True, "")
    assert is_library(target)
    assert tool.create_library(target) == (True, "")  # already a library
    busy = tmp_path / "ocupada"
    busy.mkdir()
    (busy / "foto.jpg").write_bytes(b"x")
    ok, message = tool.create_library(busy)
    assert not ok and "não está vazia" in message
    broken = cli.LibraryCli(_fake_tool(tmp_path / "quebrado", (
        "print('Another program is running', file=sys.stderr); sys.exit(1)\n")))
    ok, message = broken.create_library(tmp_path / "falha")
    assert not ok and message == cli.LIBRARY_IN_USE
    assert not (tmp_path / "falha").exists()  # does not leave an empty folder behind


@POSIX_ONLY
def test_set_fields(tmp_path):
    log = tmp_path / "args.txt"
    tool = cli.LibraryCli(_fake_tool(tmp_path / "tool", (
        f"open({str(log)!r}, 'w').write('|'.join(sys.argv[1:]))\n"
        "sys.exit(1 if '999' in sys.argv else 0)\n")))
    fields = {"title": "Spider-Geddon: Prólogo", "sort": "Spider-Geddon: Prólogo"}
    assert tool.set_fields(tmp_path, 9, fields) == (True, "")
    assert log.read_text() == (f"set_metadata|--with-library|{tmp_path}|"
                               "--field=title:Spider-Geddon: Prólogo|"
                               "--field=sort:Spider-Geddon: Prólogo|9")
    assert tool.set_fields(tmp_path, 999, {"title": "x"})[0] is False
