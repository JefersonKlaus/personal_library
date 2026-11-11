import threading
import xml.etree.ElementTree as ET

import pytest

from pdf2calibre import organizer, planner
from pdf2calibre.models import Mode, Options, Status


def _prepare(tmp_path, make_pdf, options, names=("Autor Um - Livro Um.pdf",)):
    for name in names:
        make_pdf(tmp_path / "src" / name, text=name)
    files = planner.find_pdfs([tmp_path / "src"])
    entries = planner.build_entries(files, options)
    planner.mark_duplicates(entries, options)
    dest = tmp_path / "out"
    planner.assign_targets(entries, dest, options)
    return entries, dest


def test_copy_creates_book_and_opf(tmp_path, make_pdf, options):
    entries, dest = _prepare(tmp_path, make_pdf, options)
    report = organizer.organize(entries, dest, options)
    target = entries[0].target_file
    assert (report.done, report.failed) == (1, 0)
    assert target.is_file()
    assert entries[0].source.is_file()  # copiar mantém a origem
    assert entries[0].status is Status.DONE
    opf = ET.parse(target.with_suffix(".opf")).getroot()  # nome que o Calibre procura
    assert opf.tag.endswith("package")
    assert report.manifest and report.manifest.is_file()
    assert not list(dest.rglob("*.part"))


def test_move_removes_source(tmp_path, make_pdf):
    options = Options(workers=1, mode=Mode.MOVE)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    organizer.organize(entries, dest, options)
    assert entries[0].target_file.is_file()
    assert not entries[0].source.exists()


def test_dry_run_changes_nothing(tmp_path, make_pdf):
    options = Options(workers=1, dry_run=True)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    report = organizer.organize(entries, dest, options)
    assert report.done == 1 and report.dry_run
    assert not dest.exists()
    assert entries[0].status is Status.READY


def test_no_opf_when_disabled(tmp_path, make_pdf):
    options = Options(workers=1, write_opf=False)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    organizer.organize(entries, dest, options)
    assert not list(dest.rglob("*.opf"))


def test_flat_layout_writes_sidecar_next_to_file(tmp_path, make_pdf):
    options = Options(workers=1, folder_per_book=False)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    organizer.organize(entries, dest, options)
    assert (dest / "Livro Um - Autor Um.opf").is_file()


def test_undo_copy_removes_everything(tmp_path, make_pdf, options):
    entries, dest = _prepare(tmp_path, make_pdf, options)
    report = organizer.organize(entries, dest, options)
    result = organizer.undo(report.manifest)
    assert result.done == 1 and result.failed == 0
    assert not (dest / "Autor Um").exists()
    assert entries[0].source.is_file()
    assert organizer.latest_manifest(dest) is None  # foi marcado como desfeito


def test_undo_move_restores_source(tmp_path, make_pdf):
    options = Options(workers=1, mode=Mode.MOVE)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    source = entries[0].source
    report = organizer.organize(entries, dest, options)
    assert not source.exists()
    result = organizer.undo(report.manifest)
    assert result.failed == 0
    assert source.is_file()


def test_undo_move_never_overwrites(tmp_path, make_pdf):
    options = Options(workers=1, mode=Mode.MOVE)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    source = entries[0].source
    report = organizer.organize(entries, dest, options)
    source.write_bytes(b"outro conteudo")
    result = organizer.undo(report.manifest)
    assert result.failed == 1
    assert source.read_bytes() == b"outro conteudo"
    assert entries[0].target_file.is_file()


def test_latest_manifest_picks_newest(tmp_path):
    folder = tmp_path / organizer.MANIFEST_DIR
    folder.mkdir()
    (folder / "manifest-20240101-000000-000001.json").write_text("{}")
    (folder / "manifest-20240202-000000-000001.json").write_text("{}")
    (folder / "manifest-20240303-000000-000001.undone.json").write_text("{}")
    assert organizer.latest_manifest(tmp_path).name.startswith("manifest-20240202")


def test_changed_source_is_detected_and_cleaned(tmp_path, make_pdf, options):
    entries, dest = _prepare(tmp_path, make_pdf, options)
    entries[0].source.write_bytes(entries[0].source.read_bytes() + b"\n%extra")
    report = organizer.organize(entries, dest, options)
    assert report.failed == 1
    assert entries[0].status is Status.FAILED
    assert not dest.exists() or not list(dest.rglob("*.pdf"))
    assert not list(dest.rglob("*.part"))


def test_one_failure_does_not_stop_the_batch(tmp_path, make_pdf, options):
    entries, dest = _prepare(
        tmp_path, make_pdf, options, names=("Autor Um - A.pdf", "Autor Dois - B.pdf"))
    entries[0].source.unlink()
    report = organizer.organize(entries, dest, options)
    assert (report.done, report.failed) == (1, 1)
    assert entries[1].target_file.is_file()


def test_cancel_stops_before_processing(tmp_path, make_pdf, options):
    entries, dest = _prepare(tmp_path, make_pdf, options)
    cancel = threading.Event()
    cancel.set()
    report = organizer.organize(entries, dest, options, cancel=cancel)
    assert report.cancelled and report.done == 0


def test_progress_is_reported(tmp_path, make_pdf, options):
    entries, dest = _prepare(
        tmp_path, make_pdf, options, names=("Autor Um - A.pdf", "Autor Dois - B.pdf"))
    calls = []
    organizer.organize(entries, dest, options, progress=lambda d, t, m: calls.append((d, t)))
    assert calls == [(1, 2), (2, 2)]


def test_insufficient_space_is_refused(tmp_path, make_pdf, options, monkeypatch):
    entries, dest = _prepare(tmp_path, make_pdf, options)

    class Usage:
        free = 10

    monkeypatch.setattr(organizer.shutil, "disk_usage", lambda _path: Usage)
    with pytest.raises(organizer.OrganizerError, match="Espaço insuficiente"):
        organizer.organize(entries, dest, options)
    assert not list(dest.rglob("*.pdf"))


def test_skipped_counts_unusable_entries(tmp_path, make_pdf, options):
    entries, dest = _prepare(tmp_path, make_pdf, options)
    entries[0].selected = False
    report = organizer.organize(entries, dest, options)
    assert report.skipped == 1 and report.total == 0
    assert report.summary().startswith("0 de 0")


def test_sidecars_exist_before_the_pdf_appears(tmp_path, make_pdf, monkeypatch):
    """A adição automática do Calibre não pode ver o PDF sem o OPF ao lado."""
    options = Options(workers=1, extract_cover=True)
    entries, dest = _prepare(tmp_path, make_pdf, options)
    seen = {}
    real_replace = organizer.os.replace

    def spy(src, dst):
        if str(dst).endswith(".pdf"):
            seen["opf"] = entries[0].target_file.with_suffix(".opf").is_file()
        real_replace(src, dst)

    monkeypatch.setattr(organizer.os, "replace", spy)
    organizer.organize(entries, dest, options)
    assert seen == {"opf": True}


def test_sidecar_failure_leaves_nothing_behind(tmp_path, make_pdf, options, monkeypatch):
    entries, dest = _prepare(tmp_path, make_pdf, options)

    def broken(path, *_args, **_kwargs):
        path.write_text("meio")
        raise OSError("disco cheio")

    monkeypatch.setattr(organizer, "write_opf", broken)
    report = organizer.organize(entries, dest, options)
    assert report.failed == 1 and report.manifest is None
    assert not (dest / "Autor Um").exists()


@pytest.mark.parametrize("inside", ["", "Sub/Pasta"])
def test_refuses_destination_inside_calibre_library(tmp_path, make_pdf, options, inside):
    entries, _dest = _prepare(tmp_path, make_pdf, options)
    library = tmp_path / "Calibre Library"
    library.mkdir()
    (library / "metadata.db").write_bytes(b"")
    dest = library / inside
    planner.assign_targets(entries, dest, options)
    for dry_run in (True, False):
        options.dry_run = dry_run
        with pytest.raises(organizer.OrganizerError, match="biblioteca do Calibre"):
            organizer.organize(entries, dest, options)
    assert not list(library.rglob("*.pdf"))
