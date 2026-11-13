"""Starting a reader window: a separate process, also under `flet run`."""
import os
import subprocess
import sys

import pytest


# ---------------------------------------------------------------- starting the process

def test_window_size_fits_the_screen(ui):
    size = ui.reader_launcher.window_size
    assert size(None) == (688, 860)
    assert size(1400) == (800, 1000)  # big screen: 1000 at most
    assert size(728) == (534, 668)  # laptop: shorter than the app window
    assert size(300) == (384, 480)  # never too small to read


def test_open_window_command(ui, tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(ui.reader_launcher.subprocess, "Popen",
                        lambda command, **options: started.append((command, options)))
    monkeypatch.setattr(ui.reader_launcher, "ERRORS_FILE", tmp_path / "app" / "errors.log")
    pdf = tmp_path / "Dom Casmurro.pdf"
    ui.reader_launcher.open_window(pdf, "Dom Casmurro", 900)
    [(command, options)] = started
    # a window that fails to start leaves its error in a file (it has no console)
    assert options["stderr"].name == str(tmp_path / "app" / "errors.log")
    assert options["stderr"].closed  # the app does not keep the file open
    assert command == [sys.executable, "-m", "src.ui.reader_window", "--title",
                       "Dom Casmurro", "--width", "672", "--height", "840", str(pdf)]
    root = str(ui.reader_launcher.PROJECT_ROOT)
    assert options["cwd"] == root and options["env"]["PYTHONPATH"].split(os.pathsep)[0] == root
    assert options["stdout"] == subprocess.DEVNULL  # never blocks on a full pipe
    if os.name == "nt":
        assert options["creationflags"] == subprocess.CREATE_NO_WINDOW
    else:
        assert options["start_new_session"]


def test_packaged_app_cannot_start_a_window(ui, tmp_path, monkeypatch):
    """Packaged, the executable is the app itself: running it would open a second copy
    of the app, so the book is read inside the app window instead."""
    started = []
    monkeypatch.setattr(ui.reader_launcher.subprocess, "Popen",
                        lambda *args, **kwargs: started.append(args))
    monkeypatch.setattr(ui.reader_launcher, "ERRORS_FILE", tmp_path / "errors.log")
    monkeypatch.setattr(ui.reader_launcher.sys, "frozen", True, raising=False)
    with pytest.raises(OSError):
        ui.reader_launcher.open_window(tmp_path / "a.pdf", "A")
    monkeypatch.setattr(ui.reader_launcher.sys, "frozen", False)
    for executable in ("C:/Program Files/Personal Library/personal_library.exe", ""):
        monkeypatch.setattr(ui.reader_launcher.sys, "executable", executable)
        with pytest.raises(OSError):
            ui.reader_launcher.open_window(tmp_path / "a.pdf", "A")
    assert started == []
    for executable in ("/usr/bin/python3.12", "C:/Python312/pythonw.exe"):
        monkeypatch.setattr(ui.reader_launcher.sys, "executable", executable)
        ui.reader_launcher.open_window(tmp_path / "a.pdf", "A")
    assert len(started) == 2


def test_the_module_runs_as_a_separate_process(ui):
    """The exact way the app starts it (python -m, project folder, PYTHONPATH) finds
    the module; --help stops before any window is opened."""
    options = ui.reader_launcher.process_options()
    options.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    options.pop("start_new_session", None)
    done = subprocess.run([sys.executable, "-m", "src.ui.reader_window", "--help"],
                          timeout=60, **options)
    assert done.returncode == 0, done.stderr
    assert "Janela de leitura" in done.stdout


# ---------------------------------------------------------------- started by `flet run`

FLET_RUN_ENV = {  # what `flet run` gives the app it runs (captured from flet 1.0.5)
    "FLET_SERVER_UDS_PATH": "/tmp/app-socket", "FLET_SERVER_PORT": "53211",
    "FLET_DISPLAY_URL_PREFIX": "PAGE_URL_1794533481.70", "FLET_APP_STORAGE_DATA": "/x",
}


def test_reader_does_not_inherit_the_variables_of_flet_run(ui, monkeypatch):
    """With them the reader waited for a `flet run` that never came: no window, and a
    hidden process left running at each Abrir livro."""
    for name, value in FLET_RUN_ENV.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("FLET_VIEW_PATH", "/opt/flet-client")  # a real choice: kept
    env = ui.reader_launcher.reader_environment()
    for name in ("FLET_SERVER_UDS_PATH", "FLET_SERVER_PORT", "FLET_DISPLAY_URL_PREFIX"):
        assert name not in env
    assert env["FLET_VIEW_PATH"] == "/opt/flet-client"
    assert env["FLET_APP_STORAGE_DATA"] == "/x"
    assert ui.reader_launcher.process_options()["env"] == env


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="the stand-in Flet client is a Linux executable")
def test_under_flet_run_the_reader_really_launches_its_window(ui, tmp_path, monkeypatch):
    """End to end, as on the user's machine: the app runs under `flet run` and starts a
    reader. The reader must launch the Flet client (the window) for a server of its own;
    a stand-in client (FLET_VIEW_PATH) records how it was launched and exits."""
    for name, value in FLET_RUN_ENV.items():
        monkeypatch.setenv(name, value)
    client = tmp_path / "client"
    client.mkdir()
    launched = tmp_path / "launched.txt"
    (client / "flet").write_text(
        f"#!{sys.executable}\nimport sys\nopen({str(launched)!r}, 'w').write(sys.argv[1])\n")
    (client / "flet").chmod(0o755)
    monkeypatch.setenv("FLET_VIEW_PATH", str(client))
    monkeypatch.setattr(ui.reader_launcher, "ERRORS_FILE", tmp_path / "errors.log")
    pdf = tmp_path / "livro.pdf"
    from reportlab.pdfgen import canvas
    canvas.Canvas(str(pdf)).save()
    process = ui.reader_launcher.open_window(pdf, "Livro", 900)
    try:
        assert process.wait(60) == 0, (tmp_path / "errors.log").read_text()
    finally:
        process.kill()
    page_url = launched.read_text()
    assert page_url and FLET_RUN_ENV["FLET_SERVER_UDS_PATH"] not in page_url  # its own
