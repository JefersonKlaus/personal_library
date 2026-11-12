"""Registro em arquivo: as mensagens dos módulos do app chegam ao app.log."""
import logging
from logging.handlers import RotatingFileHandler

from src.core import logging_setup
from src.importing import importer


def test_messages_from_app_modules_reach_the_log_file(tmp_path):
    log_file = tmp_path / "app.log"
    root = logging.getLogger(logging_setup.APP_LOGGER)
    before = list(root.handlers)
    try:
        assert logging_setup.setup_logging(log_file) == log_file
        # um módulo qualquer do app, em um subpacote: o logger dele precisa estar abaixo
        # do logger configurado (se o pacote mudar de nome, isto pega o problema)
        importer.logger.info("mensagem de teste")
        for handler in root.handlers:
            handler.flush()
        assert "mensagem de teste" in log_file.read_text(encoding="utf-8")
    finally:
        for handler in root.handlers[:]:
            if handler not in before:
                root.removeHandler(handler)
                handler.close()


def test_unwritable_log_folder_is_not_an_error(tmp_path):
    blocker = tmp_path / "arquivo"
    blocker.write_text("não é pasta")
    assert logging_setup.setup_logging(blocker / "app.log") is None
    assert not any(isinstance(h, RotatingFileHandler) and h.baseFilename.startswith(str(blocker))
                   for h in logging.getLogger(logging_setup.APP_LOGGER).handlers)
