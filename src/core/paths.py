"""Onde o app guarda os próprios arquivos (preferências, registro, cache)."""
from pathlib import Path

APP_DIR = Path.home() / ".personal_library"
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_FILE = APP_DIR / "app.log"
THUMBS_DIR = APP_DIR / "thumbs"  # miniaturas das capas da galeria
IMPORTS_DIR = APP_DIR / "imports"  # registros para "Desfazer última importação"
