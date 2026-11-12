"""Preferências do usuário salvas em ~/.personal_library/settings.json."""
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
    """O que o app lembra entre uma execução e outra."""

    library: str = ""  # biblioteca usada pelas três abas
    cli_path: str = ""  # ferramenta da biblioteca, se não for achada sozinha
    destination: str = ""  # pasta da aba Exportar
    gallery_sort: str = "added"
    export_folder_per_book: bool = True
    export_opf: bool = True
    export_cover: bool = True
    ai_enabled: bool = False  # "Usar Groq AI" na aba Importar
    groq_api_key: str = ""  # guardada em texto puro no settings.json do usuário
    groq_model: str = DEFAULT_MODEL
    last_sources: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def get_options(self) -> ImportOptions:
        return ImportOptions.from_dict(self.options)

    def set_options(self, options: ImportOptions) -> None:
        self.options = options.to_dict()


def load_settings(path: Path = SETTINGS_FILE) -> Settings:
    """Lê as preferências; arquivo ausente, corrompido ou com tipos errados vira padrão."""
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
