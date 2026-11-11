import json
import os
import stat
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

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
    assert creators[0].attrib[f"{{{NS['opf']}}}file-as"] == "Lima, Ana"
    assert root.find(".//dc:language", NS).text == "por"
    assert root.find(".//dc:date", NS).text.startswith("2019-01-01")
    assert [s.text for s in root.findall(".//dc:subject", NS)] == ["importado"]
    assert root.find(".//{http://www.idpf.org/2007/opf}reference").attrib["href"] == "cover.jpg"


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

def test_build_add_command_uses_equals_form():
    entry = _entry(title="-Perigo", target_file=Path("/lib/x.pdf"))
    command = calibre.build_add_command(
        Path("/bin/calibredb"), Path("/lib"), entry, Options(tags=["a", "b"]), Path("/lib/cover.jpg"))
    assert command[:4] == ["/bin/calibredb", "add", "--with-library", "/lib"]
    assert "--title=-Perigo" in command
    assert "--authors=Ana Lima & Rui Dias" in command
    assert "--tags=a,b" in command and "--cover=/lib/cover.jpg" in command
    assert "--duplicates" not in command
    assert command[-1] == "/lib/x.pdf"


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
