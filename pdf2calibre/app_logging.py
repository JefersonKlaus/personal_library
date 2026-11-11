"""Registro em arquivo para investigar problemas (~/.pdf2calibre/app.log)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .settings import CONFIG_DIR


def setup_logging(directory: Path = CONFIG_DIR) -> Path | None:
    """Configura um log rotativo; devolve o caminho ou None se não der para gravar."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        log_path = directory / "app.log"
        handler = RotatingFileHandler(log_path, maxBytes=500_000, backupCount=2,
                                      encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("pdf2calibre")
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return log_path
