import pytest

from personal_library import files


def test_sha256_is_stable(tmp_path):
    file = tmp_path / "a.bin"
    file.write_bytes(b"abc")
    assert files.sha256_file(file) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_copy_verified_copies_and_checks(tmp_path):
    source = tmp_path / "livro.pdf"
    source.write_bytes(b"%PDF conteudo")
    target = tmp_path / "copia.pdf"
    files.copy_verified(source, target, files.sha256_file(source))
    assert target.read_bytes() == source.read_bytes()


def test_changed_source_is_detected_and_not_left_behind(tmp_path):
    """O PDF mudou depois da análise (hash diferente): a cópia é recusada e apagada."""
    source = tmp_path / "livro.pdf"
    source.write_bytes(b"%PDF original")
    expected = files.sha256_file(source)
    source.write_bytes(b"%PDF alterado depois")
    target = tmp_path / "copia.pdf"
    with pytest.raises(files.FileOperationError, match="diferente"):
        files.copy_verified(source, target, expected)
    assert not target.exists()


def test_insufficient_space_is_refused(tmp_path, monkeypatch):
    class Usage:
        free = 10

    monkeypatch.setattr(files.shutil, "disk_usage", lambda _path: Usage)
    with pytest.raises(files.FileOperationError, match="Espaço insuficiente"):
        files.ensure_free_space(tmp_path, 1_000)
    files.ensure_free_space(tmp_path, 1)  # cabe


def test_make_dirs_and_remove_empty_dirs(tmp_path):
    created = files.make_dirs(tmp_path / "a" / "b" / "c")
    assert created == [str(tmp_path / "a"), str(tmp_path / "a" / "b"),
                       str(tmp_path / "a" / "b" / "c")]
    (tmp_path / "a" / "fica.txt").write_text("x")
    files.remove_empty_dirs(created)
    assert not (tmp_path / "a" / "b").exists()
    assert (tmp_path / "a" / "fica.txt").exists()  # pasta com conteúdo continua


def test_manifest_undo_removes_what_was_created(tmp_path):
    folder = tmp_path / "out" / "Autor" / "Livro"
    created = files.make_dirs(folder)
    made = [folder / "Livro - Autor.pdf", folder / "Livro - Autor.opf"]
    for path in made:
        path.write_text("x")
    manifest = files.write_manifest(tmp_path / "out", [files.CreatedFiles(
        [str(p) for p in made], created)])
    assert files.latest_manifest(tmp_path / "out") == manifest
    report = files.undo_manifest(manifest)
    assert (report.done, report.failed) == (1, 0)
    assert not (tmp_path / "out" / "Autor").exists()
    assert files.latest_manifest(tmp_path / "out") is None  # marcado como desfeito


def test_latest_manifest_picks_newest(tmp_path):
    folder = tmp_path / files.MANIFEST_DIR
    folder.mkdir()
    (folder / "manifest-20240101-000000-000001.json").write_text("{}")
    (folder / "manifest-20240202-000000-000001.json").write_text("{}")
    (folder / "manifest-20240303-000000-000001.undone.json").write_text("{}")
    assert files.latest_manifest(tmp_path).name.startswith("manifest-20240202")
    assert files.latest_manifest(tmp_path / "nada") is None
