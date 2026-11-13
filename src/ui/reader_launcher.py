"""Starting a reader window (the app side): a separate process, because Flet 1.0 has one
window per app. The window itself is reader_window.py, started as

    python -m src.ui.reader_window --title "Dom Casmurro" ".../Dom Casmurro.pdf"

The app does not wait for it, several books can be open at once, and closing a reader
window (or the app) does not close the others.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.paths import LOG_FILE

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # the folder that contains src/
MODULE = "src.ui.reader_window"  # the window program
DEFAULT_HEIGHT = 860
# Where a reader window that fails to start leaves its error (it has no console).
ERRORS_FILE = LOG_FILE.with_name("reader-errors.log")
# Set by `flet run` for the app it runs: "do not open a window, flet run connects to this
# server". Inherited by the reader process, they made it wait for a `flet run` that never
# came: no window, and a hidden process left running at each "Abrir livro".
FLET_RUN_VARIABLES = ("FLET_DISPLAY_URL_PREFIX", "FLET_SERVER_PORT", "FLET_SERVER_IP",
                      "FLET_SERVER_UDS_PATH", "FLET_FORCE_WEB_SERVER", "FLET_WEB_APP_PATH",
                      "FLET_WEB_PATH")


def window_size(screen_height: float | None) -> tuple[int, int]:
    """(width, height) of a new reader window: a page fits, and the window is not taller
    than the app window (so it fits on small screens too)."""
    height = DEFAULT_HEIGHT
    if screen_height:
        height = int(max(480, min(1000, screen_height - 60)))
    return int(height * 0.8), height


def reader_environment() -> dict[str, str]:
    """The app's environment without the variables of `flet run`, so the reader opens a
    window of its own, plus the project folder on PYTHONPATH (so `-m src...` is found)."""
    env = {name: value for name, value in os.environ.items()
           if name not in FLET_RUN_VARIABLES}
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(PROJECT_ROOT),
                                                      os.environ.get("PYTHONPATH")]))
    return env


def process_options() -> dict[str, Any]:
    """How the reader process is started: from the project folder, in its own environment
    (`reader_environment`), without a console window on Windows, and not tied to the
    app's terminal."""
    options: dict[str, Any] = {
        "cwd": str(PROJECT_ROOT), "env": reader_environment(),
        "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:  # Ctrl+C in the terminal of `flet run` does not close the reader windows
        options["start_new_session"] = True
    return options


def open_window(path: Path, title: str, screen_height: float | None = None) -> subprocess.Popen:
    """Starts the reader window and returns at once. Raises OSError when a separate
    process is not possible (e.g. a packaged app, which has no Python to run it)."""
    # Packaged app: sys.executable is the app itself (or nothing), and running it would
    # open a second copy of the app instead of a reader window.
    interpreter = Path(sys.executable or "").name.lower()
    if getattr(sys, "frozen", False) or not interpreter.startswith("python"):
        raise OSError("o app empacotado não abre janelas extras")
    width, height = window_size(screen_height)
    command = [sys.executable, "-m", MODULE, "--title", title, "--width", str(width),
               "--height", str(height), str(path)]
    options = process_options()
    errors = None
    try:
        ERRORS_FILE.parent.mkdir(parents=True, exist_ok=True)
        errors = ERRORS_FILE.open("a", encoding="utf-8")
        options["stderr"] = errors
    except OSError:  # no log file: the window still opens
        logger.debug("cannot write %s", ERRORS_FILE, exc_info=True)
    try:
        return subprocess.Popen(command, **options)
    finally:
        if errors is not None:
            errors.close()  # the reader process has its own copy
