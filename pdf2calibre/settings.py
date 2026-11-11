"""Preferências do usuário salvas em ~/.pdf2calibre/settings.json (Personal Library)."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import Options

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".pdf2calibre"
SETTINGS_FILE = CONFIG_DIR / "settings.json"


@dataclass
class Settings:
    """O que o app lembra entre uma execução e outra."""

    destination: str = ""
    library: str = ""
    calibredb: str = ""
    use_calibredb: bool = False
    gallery_sort: str = "added"
    export_folder_per_book: bool = True
    export_opf: bool = True
    export_cover: bool = True
    last_sources: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def get_options(self) -> Options:
        return Options.from_dict(self.options)

    def set_options(self, options: Options) -> None:
        self.options = options.to_dict()


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    """Lê as preferências; arquivo ausente ou corrompido resulta nos padrões."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    settings = Settings()
    for key in ("destination", "library", "calibredb", "gallery_sort"):
        if isinstance(raw.get(key), str):
            setattr(settings, key, raw[key])
    settings.use_calibredb = bool(raw.get("use_calibredb", False))
    for key in ("export_folder_per_book", "export_opf", "export_cover"):
        if isinstance(raw.get(key), bool):
            setattr(settings, key, raw[key])
    sources = raw.get("last_sources")
    if isinstance(sources, list):
        settings.last_sources = [item for item in sources if isinstance(item, str)]
    if isinstance(raw.get("options"), dict):
        settings.options = raw["options"]
    return settings


def save_settings(settings: Settings, path: Path = SETTINGS_FILE) -> bool:
    """Grava as preferências; devolve False se não conseguir (não é crítico)."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2),
                        encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("Não foi possível salvar as preferências: %s", exc)
        return False
