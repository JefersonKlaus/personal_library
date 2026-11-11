import threading

from pdf2calibre import planner
from pdf2calibre.models import Options, Status


def _scan(root, options, **kwargs):
    files = planner.find_pdfs([root], options.recursive, **kwargs)
    return planner.build_entries(files, options)


def test_find_pdfs_recursive_and_filters(make_pdf, tmp_path):
    make_pdf(tmp_path / "a.pdf")
    make_pdf(tmp_path / "sub" / "b.PDF")
    make_pdf(tmp_path / ".oculta" / "c.pdf")
    (tmp_path / "nota.txt").write_text("x")
    (tmp_path / "._lixo.pdf").write_bytes(b"x")
    names = [p.name for p in planner.find_pdfs([tmp_path])]
    assert names == ["a.pdf", "b.PDF"]


def test_find_pdfs_not_recursive_and_dedup(make_pdf, tmp_path):
    first = make_pdf(tmp_path / "a.pdf")
    make_pdf(tmp_path / "sub" / "b.pdf")
    found = planner.find_pdfs([tmp_path, first], recursive=False)
    assert [p.name for p in found] == ["a.pdf"]


def test_find_pdfs_excludes_destination(make_pdf, tmp_path):
    make_pdf(tmp_path / "a.pdf")
    make_pdf(tmp_path / "biblioteca" / "b.pdf")
    found = planner.find_pdfs([tmp_path], exclude=tmp_path / "biblioteca")
    assert [p.name for p in found] == ["a.pdf"]


def test_find_pdfs_natural_order(make_pdf, tmp_path):
    for name in ("livro10.pdf", "livro2.pdf", "livro1.pdf"):
        make_pdf(tmp_path / name)
    assert [p.name for p in planner.find_pdfs([tmp_path])] == [
        "livro1.pdf", "livro2.pdf", "livro10.pdf"]


def test_build_entries_keeps_order_and_reports_progress(make_pdf, tmp_path, options):
    for index in range(5):
        make_pdf(tmp_path / f"Autor {index} - Livro {index}.pdf", text=f"t{index}")
    seen = []
    files = planner.find_pdfs([tmp_path])
    entries = planner.build_entries(files, options, lambda d, t, m: seen.append((d, t)))
    assert [e.source for e in entries] == files
    assert seen[-1] == (5, 5)


def test_build_entries_cancel(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "a.pdf")
    cancel = threading.Event()
    cancel.set()
    assert planner.build_entries(planner.find_pdfs([tmp_path]), options, cancel=cancel) == []


def test_identical_files_are_duplicates(make_pdf, tmp_path, options):
    original = make_pdf(tmp_path / "Autor Um - Livro.pdf", text="igual")
    (tmp_path / "Autor Um - Livro copia.pdf").write_bytes(original.read_bytes())
    entries = _scan(tmp_path, options)
    assert planner.mark_duplicates(entries, options) == 1
    assert [e.status for e in entries] == [Status.READY, Status.DUPLICATE]
    assert entries[1].selected is False


def test_duplicate_keeps_the_copy_with_better_metadata(make_pdf, tmp_path, options):
    # "Livros/..." vem antes na ordem das pastas, mas não tem autor
    original = make_pdf(tmp_path / "Machado de Assis - Dom Casmurro.pdf", text="igual")
    (tmp_path / "Livros").mkdir()
    (tmp_path / "Livros" / "Dom Casmurro - copia.pdf").write_bytes(original.read_bytes())
    entries = _scan(tmp_path, options)
    assert entries[0].source.parent.name == "Livros"  # confirma a ordem do cenário
    planner.mark_duplicates(entries, options)
    kept = [e for e in entries if e.usable]
    assert [e.source.name for e in kept] == ["Machado de Assis - Dom Casmurro.pdf"]
    assert entries[0].status is Status.DUPLICATE
    assert "idêntico a Machado de Assis - Dom Casmurro.pdf" in entries[0].notes


def test_duplicates_only_noted_when_not_skipping(make_pdf, tmp_path):
    options = Options(workers=1, skip_duplicates=False)
    original = make_pdf(tmp_path / "Autor Um - Livro.pdf", text="igual")
    (tmp_path / "Autor Um - Livro copia.pdf").write_bytes(original.read_bytes())
    entries = _scan(tmp_path, options)
    planner.mark_duplicates(entries, options)
    assert all(e.usable for e in entries)
    assert any("idêntico" in n for n in entries[1].notes)


def test_same_title_author_different_file_warns(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "Autor Um - Livro.pdf", text="versao 1")
    make_pdf(tmp_path / "Autor Um - Livro (2019).pdf", text="versao 2")
    entries = _scan(tmp_path, options)
    planner.mark_duplicates(entries, options)
    assert entries[1].status is Status.WARNING
    assert entries[1].usable


def test_assign_targets_calibre_layout(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "src" / "Machado de Assis - Dom Casmurro.pdf")
    entries = _scan(tmp_path / "src", options)
    dest = tmp_path / "out"
    planner.assign_targets(entries, dest, options)
    expected = dest / "Machado de Assis" / "Dom Casmurro" / "Dom Casmurro - Machado de Assis.pdf"
    assert entries[0].target_file == expected


def test_assign_targets_flat_layout(make_pdf, tmp_path):
    options = Options(workers=1, folder_per_book=False)
    make_pdf(tmp_path / "src" / "Autor Um - Livro.pdf")
    entries = _scan(tmp_path / "src", options)
    planner.assign_targets(entries, tmp_path / "out", options)
    assert entries[0].target_file == tmp_path / "out" / "Livro - Autor Um.pdf"


def test_assign_targets_avoids_collisions(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "src" / "a" / "Autor Um - Livro.pdf", text="um")
    make_pdf(tmp_path / "src" / "b" / "Autor Um - Livro.pdf", text="dois")
    entries = _scan(tmp_path / "src", options)
    planner.assign_targets(entries, tmp_path / "out", options)
    dirs = {e.target_dir for e in entries}
    assert len(dirs) == 2
    assert any(d.name == "Livro (2)" for d in dirs)


def test_assign_targets_marks_existing_identical(make_pdf, tmp_path, options):
    source = make_pdf(tmp_path / "src" / "Autor Um - Livro.pdf")
    dest = tmp_path / "out"
    existing = dest / "Autor Um" / "Livro" / "Livro - Autor Um.pdf"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(source.read_bytes())
    entries = _scan(tmp_path / "src", options)
    planner.assign_targets(entries, dest, options)
    assert entries[0].status is Status.EXISTS
    # mudar o destino reavalia
    planner.assign_targets(entries, tmp_path / "outro", options)
    assert entries[0].status is Status.READY
    assert entries[0].target_file is not None


def test_summarize_counts_by_status(make_pdf, tmp_path, options):
    make_pdf(tmp_path / "Autor Um - Livro.pdf")
    (tmp_path / "vazio.pdf").write_bytes(b"")
    counts = planner.summarize(_scan(tmp_path, options))
    assert counts[Status.READY] == 1
    assert counts[Status.ERROR] == 1
