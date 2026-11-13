"""User settings saved in ~/.personal_library/settings.json."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from ..importing.groq_client import DEFAULT_MODEL
from .models import ImportOptions
from .paths import SETTINGS_FILE

logger = logging.getLogger(__name__)


@dataclass
class Settings:
    """What the app remembers between one run and the next."""

    library: str = ""  # library used by the three tabs
    cli_path: str = ""  # library tool, when it is not found on its own
    destination: str = ""  # folder of the Export tab
    gallery_sort: str = "added"
    export_folder_per_book: bool = True
    export_opf: bool = True
    export_cover: bool = True
    ai_enabled: bool = False  # "Usar Groq AI" in the Import tab
    groq_api_key: str = ""  # kept as plain text in the user's settings.json
    groq_model: str = DEFAULT_MODEL
    last_sources: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def get_options(self) -> ImportOptions:
        return ImportOptions.from_dict(self.options)

    def set_options(self, options: ImportOptions) -> None:
        self.options = options.to_dict()


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    """Reads the settings; a missing, corrupt or wrongly typed file falls back to defaults."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    settings = Settings()
    for item in fields(Settings):
        value, default = raw.get(item.name), getattr(settings, item.name)
        if value is not None and isinstance(value, type(default)):
            setattr(settings, item.name, value)
    settings.last_sources = [s for s in settings.last_sources if isinstance(s, str)]
    return settings


def save_settings(settings: Settings, path: Path = SETTINGS_FILE) -> bool:
    """Writes the settings; returns False if it cannot (not critical)."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("Could not save the settings: %s", exc)
        return False
