"""Where the app keeps its own files (settings, log, cache)."""
from pathlib import Path

APP_DIR = Path.home() / ".personal_library"
SETTINGS_FILE = APP_DIR / "settings.json"
LOG_FILE = APP_DIR / "app.log"
THUMBS_DIR = APP_DIR / "thumbs"  # gallery cover thumbnails
IMPORTS_DIR = APP_DIR / "imports"  # records for "Desfazer última importação"
