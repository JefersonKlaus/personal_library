import json
import os
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath, PureWindowsPath

import pytest

from pdf2calibre import calibre, cover, opf, settings
from pdf2calibre.models import BookEntry, Mode, Options

NS = {"dc": "http://purl.org/dc/elements/1.1/", "opf": "http://www.idpf.org/2007/opf"}


def _entry(**kwargs) -> BookEntry:
    data = dict(source=Path("/tmp/x.pdf"), title="A & B <Teste>", author="Ana Lima & Rui Dias",
                year=2019, language="pt", sha256="ab" * 32)
    data.update(kwargs)
    return BookEntry(**data)


# ---------- OPF ----------

def test_opf_is_valid_xml_with_escaping():
    root = ET.fromstring(opf.build_opf(_entry(), tags=["importado", " "], cover_name="cover.jpg"))
    assert root.find(".//dc:title", NS).text == "A & B <Teste>"
    creators = root.findall(".//dc:creator", NS)
    assert [c.text for c in creators] == ["Ana Lima", "Rui Dias"]
    # convenção do Calibre: o author_sort do livro inteiro em todos os criadores
    file_as = {c.attrib[f"{{{NS['opf']}}}file-as"] for c in creators}
    assert file_as == {"Lima, Ana & Dias, Rui"}
    assert root.find(".//dc:language", NS).text == "por"
    # meio-dia UTC: continua 2019 em qualquer fuso (meia-noite viraria 2018 no Brasil)
    assert root.find(".//dc:date", NS).text == "2019-01-01T12:00:00+00:00"
    assert [s.text for s in root.findall(".//dc:subject", NS)] == ["importado"]
    assert root.find(".//{http://www.idpf.org/2007/opf}reference").attrib["href"] == "cover.jpg"


def test_opf_has_the_identifier_calibre_requires():
    """Sem <dc:identifier opf:scheme="calibre"> o Calibre ignora o OPF inteiro."""
    root = ET.fromstring(opf.build_opf(_entry()))
    schemes = {node.attrib.get(f"{{{NS['opf']}}}scheme"): (node.text or "").strip()
               for node in root.findall(".//dc:identifier", NS)}
    assert schemes["calibre"]
    assert schemes["uuid"]
    assert root.attrib["unique-identifier"] == "uuid_id"


def test_opf_identifier_is_deterministic_and_omits_unknown_language():
    first = opf.build_opf(_entry(language=None))
    assert first == opf.build_opf(_entry(language=None))
    assert "<dc:language>" not in first
    assert ET.fromstring(first).find(".//dc:title", NS) is not None
    assert opf.language_code("XX") == "xx"
    assert opf.language_code(None) is None


def test_write_opf_creates_utf8_file(tmp_path):
    path = opf.write_opf(tmp_path / "metadata.opf", _entry(title="Coração"))
    assert "Coração" in path.read_text(encoding="utf-8")


# ---------- Calibre ----------

@pytest.mark.parametrize("flavor", [PurePosixPath, PureWindowsPath])
def test_build_add_command_uses_equals_form(flavor):
    """Os caminhos vão no formato do sistema ('/lib' no Linux, '\\lib' no Windows)."""
    tool, library = flavor("/bin/calibredb"), flavor("/lib")
    book, cover_file = library / "x.pdf", library / "cover.jpg"
    entry = _entry(title="-Perigo", target_file=book)
    command = calibre.build_add_command(
        tool, library, entry, Options(tags=["a", "b"]), cover_file)
    assert command[:4] == [str(tool), "add", "--with-library", str(library)]
    assert "--title=-Perigo" in command
    assert "--authors=Ana Lima & Rui Dias" in command
    assert "--tags=a,b" in command and f"--cover={cover_file}" in command
    assert "--duplicates" not in command
    assert command[-1] == str(book)


def test_build_add_command_allows_duplicates_when_requested():
    command = calibre.build_add_command(
        Path("c"), Path("l"), _entry(), Options(skip_duplicates=False))
    assert "--duplicates" in command


def test_parse_added_ids():
    assert calibre.parse_added_ids("Added book ids: 12, 13") == [12, 13]
    assert calibre.parse_added_ids("nada") == []


def test_is_calibre_library(tmp_path):
    assert not calibre.is_calibre_library(tmp_path)
    (tmp_path / "metadata.db").write_bytes(b"")
    assert calibre.is_calibre_library(tmp_path)


def test_find_library_root(tmp_path):
    assert calibre.find_library_root(tmp_path / "x") is None
    (tmp_path / "metadata.db").write_bytes(b"")
    assert calibre.find_library_root(tmp_path) == tmp_path.absolute()
    assert calibre.find_library_root(tmp_path / "Autor" / "Livro") == tmp_path.absolute()


def test_find_calibredb_custom_and_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(calibre, "_KNOWN_DIRS", ())
    assert calibre.find_calibredb() is None
    fake = tmp_path / "calibredb"
    fake.write_text("x")
    assert calibre.find_calibredb(str(fake)) == fake
    assert calibre.find_calibredb(str(tmp_path)) == fake


@pytest.mark.skipif(os.name == "nt", reason="usa um script shell falso")
def test_import_entries_with_fake_calibredb(tmp_path):
    fake = tmp_path / "calibredb"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "if any('Repetido' in a for a in sys.argv):\n"
        "    print('The following books were not added'); sys.exit(0)\n"
        "if any('Quebrado' in a for a in sys.argv):\n"
        "    print('Another calibre program is running', file=sys.stderr); sys.exit(1)\n"
        "print('Added book ids: 7')\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    entries = [_entry(title="Bom"), _entry(title="Repetido"), _entry(title="Quebrado")]
    seen = []
    results = calibre.import_entries(
        entries, tmp_path, Options(), fake, progress=lambda d, t, m: seen.append(d))
    assert [r.ok for r in results] == [True, False, False]
    assert results[0].book_ids == [7]
    assert "já existe" in results[1].message
    assert "Feche o Calibre" in results[2].message
    assert seen == [1, 2, 3]


def test_import_entries_handles_missing_executable(tmp_path):
    results = calibre.import_entries(
        [_entry()], tmp_path, Options(), tmp_path / "nao-existe")
    assert results[0].ok is False
    assert "não foi possível" in results[0].message


# ---------- Settings ----------

def test_settings_roundtrip(tmp_path):
    path = tmp_path / "cfg" / "settings.json"
    saved = settings.Settings(destination="/d", library="/l", use_calibredb=True,
                              last_sources=["/a"])
    saved.set_options(Options(mode=Mode.MOVE, tags=["x"]))
    assert settings.save_settings(saved, path)
    loaded = settings.load_settings(path)
    assert (loaded.destination, loaded.library, loaded.use_calibredb) == ("/d", "/l", True)
    assert loaded.get_options().mode is Mode.MOVE
    assert loaded.get_options().tags == ["x"]


def test_settings_tolerates_corrupt_or_wrong_types(tmp_path):
    path = tmp_path / "s.json"
    path.write_text("{não é json")
    assert settings.load_settings(path) == settings.Settings()
    path.write_text(json.dumps({"destination": 5, "options": {"mode": "voar", "xyz": 1},
                                "last_sources": ["a", 3]}))
    loaded = settings.load_settings(path)
    assert loaded.destination == ""
    assert loaded.last_sources == ["a"]
    assert loaded.get_options().mode is Mode.COPY
    path.write_text("[1, 2]")
    assert settings.load_settings(path) == settings.Settings()


def test_missing_settings_file_gives_defaults(tmp_path):
    assert settings.load_settings(tmp_path / "nada.json") == settings.Settings()


# ---------- Capa ----------

def test_extract_cover_makes_jpeg(tmp_path, make_pdf):
    pytest.importorskip("pypdfium2")
    pytest.importorskip("PIL")
    pdf = make_pdf(tmp_path / "x.pdf")
    out = tmp_path / "cover.jpg"
    assert cover.extract_cover(pdf, out) is True
    assert out.read_bytes()[:3] == b"\xff\xd8\xff"


def test_extract_cover_fails_gracefully(tmp_path):
    bad = tmp_path / "ruim.pdf"
    bad.write_bytes(b"%PDF-1.4 lixo")
    out = tmp_path / "cover.jpg"
    assert cover.extract_cover(bad, out) is False
    assert not out.exists()


@pytest.mark.skipif(os.name == "nt", reason="usa um script shell falso")
def test_import_forces_english_output_and_finds_flat_cover(tmp_path, monkeypatch):
    """Calibre em português responde 'IDs de livro adicionados'; o app força inglês."""
    monkeypatch.setenv("CALIBRE_OVERRIDE_LANG", "pt_BR")
    fake = tmp_path / "calibredb"
    fake.write_text(
        f"#!{sys.executable}\n"
        "import os, sys\n"
        "if os.environ.get('CALIBRE_OVERRIDE_LANG') != 'en':\n"
        "    print('IDs de livro adicionados: 7'); sys.exit(0)\n"
        "print('Ação: ' + ' '.join(a for a in sys.argv if a.startswith('--cover')))\n"
        "print('Added book ids: 7')\n"
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    book = tmp_path / "Livro - Autor.pdf"
    book.write_bytes(b"%PDF-1.4")
    book.with_suffix(".jpg").write_bytes(b"jpg")
    entry = _entry(target_file=book)
    results = calibre.import_entries([entry], tmp_path, Options(folder_per_book=False), fake)
    assert results[0].ok and results[0].book_ids == [7]
    assert calibre.build_add_command(
        fake, tmp_path, entry, Options(), book.with_suffix(".jpg"))[-2].startswith("--cover=")


def test_export_settings_roundtrip(tmp_path):
    path = tmp_path / "s.json"
    saved = settings.Settings(export_folder_per_book=False, export_opf=False, export_cover=False,
                              gallery_sort="title")
    settings.save_settings(saved, path)
    loaded = settings.load_settings(path)
    assert (loaded.export_folder_per_book, loaded.export_opf, loaded.export_cover) == (
        False, False, False)
    assert loaded.gallery_sort == "title"
    path.write_text(json.dumps({"export_opf": "sim"}))
    assert settings.load_settings(path).export_opf is True  # tipo errado: padrão


def test_opf_and_calibredb_carry_series_and_volume():
    entry = _entry(title="One Punch Man - Vol 18", author="ONE", series="One Punch Man",
                   series_index=18.0, target_file=Path("/lib/x.pdf"))
    root = ET.fromstring(opf.build_opf(entry))
    metas = {m.attrib["name"]: m.attrib["content"]
             for m in root.findall(".//{http://www.idpf.org/2007/opf}meta")}
    assert metas["calibre:series"] == "One Punch Man"
    assert metas["calibre:series_index"] == "18"
    command = calibre.build_add_command(Path("c"), Path("l"), entry, Options())
    assert "--series=One Punch Man" in command and "--series-index=18" in command
    plain = calibre.build_add_command(Path("c"), Path("l"), _entry(), Options())
    assert not any(arg.startswith("--series") for arg in plain)


def test_options_pattern_type_is_checked():
    assert Options.from_dict({"filename_pattern": 5}).filename_pattern == ""
    assert Options.from_dict({"filename_pattern": "NOME - VOL"}).filename_pattern == "NOME - VOL"


def test_opf_and_calibredb_carry_fixed_tags_and_publisher():
    entry = _entry(tags=["mangá"], publisher="Panini", target_file=Path("/lib/x.pdf"))
    root = ET.fromstring(opf.build_opf(entry, tags=["importado", "mangá"]))
    assert [n.text for n in root.findall(".//dc:subject", NS)] == ["importado", "mangá"]
    assert root.find(".//dc:publisher", NS).text == "Panini"
    command = calibre.build_add_command(Path("c"), Path("l"), entry, Options(tags=["importado"]))
    assert "--tags=importado,mangá" in command


def test_volumes_are_added_with_duplicates_flag():
    """O Calibre só compara título + autor e recusaria o volume 2; o app confere antes."""
    volume = _entry(title="One Punch Man", series="One Punch Man", series_index=2.0)
    assert "--duplicates" in calibre.build_add_command(Path("c"), Path("l"), volume, Options())
    assert "--duplicates" not in calibre.build_add_command(Path("c"), Path("l"), _entry(),
                                                           Options())


# ---------- Bibliotecas: achar, escolher, criar ----------

def _library(path):
    path.mkdir(parents=True, exist_ok=True)
    (path / "metadata.db").write_bytes(b"")
    return path


def test_known_libraries_reads_calibre_config(tmp_path, monkeypatch):
    monkeypatch.setattr(calibre.Path, "home", lambda: tmp_path / "home")
    config = tmp_path / "config"
    config.mkdir()
    current, often, rare = (_library(tmp_path / n) for n in ("atual", "muito", "pouco"))
    (config / "global.py.json").write_text(json.dumps({"library_path": str(current)}))
    (config / "gui.json").write_text(json.dumps({"library_usage_stats": {
        str(rare): 1, str(tmp_path / "apagada"): 50, str(often): 9, str(current): 3}}))
    default = _library(tmp_path / "home" / "Calibre Library")
    assert calibre.known_libraries(config) == [current, often, rare, default]
    assert calibre.known_libraries(tmp_path / "sem-config") == [default]


def test_calibre_config_dir_respects_override(monkeypatch, tmp_path):
    monkeypatch.setenv("CALIBRE_CONFIG_DIRECTORY", str(tmp_path))
    assert calibre.calibre_config_dir() == tmp_path


def test_find_library_in_folder_or_single_child(tmp_path):
    lib = _library(tmp_path / "Documentos" / "Calibre Library")
    assert calibre.find_library_in(lib) == lib
    assert calibre.find_library_in(tmp_path / "Documentos") == lib
    _library(tmp_path / "Documentos" / "Outra")
    assert calibre.find_library_in(tmp_path / "Documentos") is None  # ambíguo
    assert calibre.find_library_in(tmp_path / "nao-existe") is None


def test_new_library_path(tmp_path):
    assert calibre.new_library_path(tmp_path / "nova") == tmp_path / "nova"
    empty = tmp_path / "vazia"
    empty.mkdir()
    assert calibre.new_library_path(empty) == empty
    busy = tmp_path / "Documentos"
    busy.mkdir()
    (busy / "foto.jpg").write_bytes(b"x")
    assert calibre.new_library_path(busy) == busy / "Calibre Library"
    (busy / "Calibre Library").mkdir()
    (busy / "Calibre Library" / "x").write_bytes(b"x")
    assert calibre.new_library_path(busy) == busy / "Calibre Library 2"


@pytest.mark.skipif(os.name == "nt", reason="usa um script shell falso")
def test_create_library(tmp_path):
    fake = tmp_path / "calibredb"
    fake.write_text(f"#!{sys.executable}\nimport sys, pathlib\n"
                    "lib = pathlib.Path(sys.argv[sys.argv.index('--with-library') + 1])\n"
                    "(lib / 'metadata.db').write_bytes(b'')\n")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    target = tmp_path / "nova" / "Calibre Library"
    assert calibre.create_library(fake, target) == (True, "")
    assert calibre.is_calibre_library(target)
    assert calibre.create_library(fake, target) == (True, "")  # já é biblioteca
    busy = tmp_path / "ocupada"
    busy.mkdir()
    (busy / "foto.jpg").write_bytes(b"x")
    ok, message = calibre.create_library(fake, busy)
    assert not ok and "não está vazia" in message
    broken = tmp_path / "quebrado"
    broken.write_text(f"#!{sys.executable}\nimport sys\n"
                      "print('Another calibre program is running', file=sys.stderr)\nsys.exit(1)\n")
    broken.chmod(broken.stat().st_mode | stat.S_IEXEC)
    ok, message = calibre.create_library(broken, tmp_path / "falha")
    assert not ok and "Feche o Calibre" in message
    assert not (tmp_path / "falha").exists()  # não deixa pasta vazia para trás
