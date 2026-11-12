"""Registro em arquivo para investigar problemas (~/.personal_library/app.log)."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .paths import LOG_FILE

# O logger do pacote do app ("src"): os módulos usam logging.getLogger(__name__), então
# todos ficam abaixo dele. Calculado, e não escrito à mão, para não parar de gravar
# em silêncio se o pacote mudar de nome outra vez.
APP_LOGGER = __name__.partition(".")[0]


def setup_logging(log_file: Path = LOG_FILE) -> Path | None:
    """Configura um log rotativo; devolve o caminho ou None se não der para gravar."""
    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(log_file, maxBytes=500_000, backupCount=2, encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger(APP_LOGGER)
    root.setLevel(logging.INFO)
    if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        root.addHandler(handler)
    return log_file
