from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from app.core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    settings.logs_path.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        settings.logs_path / "backend.log", maxBytes=10 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(existing, RotatingFileHandler) for existing in root.handlers):
        root.addHandler(handler)
