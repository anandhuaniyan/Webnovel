from pathlib import Path

import pytest
from app.core.config import Settings
from pydantic import ValidationError


def settings_kwargs(root: Path) -> dict:
    return {
        "project_root": root,
        "data_path": root / "data",
        "storage_path": root / "storage",
        "logs_path": root / "logs",
        "backups_path": root / "backups",
        "redis_url": "redis://localhost:6379/0",
    }


def test_database_name_is_guarded(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="database must be 'webnovel'"):
        Settings(
            database_url="postgresql://user:pass@localhost/another_project",
            **settings_kwargs(tmp_path),
        )


def test_paths_cannot_escape_project(tmp_path: Path) -> None:
    values = settings_kwargs(tmp_path)
    values["data_path"] = tmp_path.parent / "other-project"
    with pytest.raises(ValidationError, match="points outside"):
        Settings(database_url="postgresql://user:pass@localhost/webnovel", **values)


def test_psycopg_driver_is_selected(tmp_path: Path) -> None:
    settings = Settings(
        database_url="postgresql://user:pass@localhost/webnovel",
        **settings_kwargs(tmp_path),
    )
    assert settings.database_url.startswith("postgresql+psycopg://")
