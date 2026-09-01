from __future__ import annotations

import hashlib
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.core.config import get_settings


@dataclass(frozen=True)
class StorageCategory:
    name: str
    path: str
    bytes_used: int
    file_count: int


class StorageService:
    def __init__(self) -> None:
        settings = get_settings()
        self.root = settings.project_root.resolve()
        self.categories = {
            "raw_books": settings.data_path / "source-books",
            "processed_books": settings.data_path / "processed-books",
            "rights_evidence": settings.data_path / "rights-evidence",
            "covers": settings.storage_path / "covers",
            "chapter_images": settings.storage_path / "chapter-images",
            "temporary": settings.storage_path / "temporary",
            "database": self.root / "database",
            "backups": settings.backups_path,
            "logs": settings.logs_path,
        }

    def ensure_directories(self) -> None:
        for path in self.categories.values():
            self._assert_inside(path)
            path.mkdir(parents=True, exist_ok=True)

    def metrics(self) -> dict:
        values: list[StorageCategory] = []
        for name, path in self.categories.items():
            self._assert_inside(path)
            files = [item for item in path.rglob("*") if item.is_file()] if path.exists() else []
            values.append(
                StorageCategory(name, str(path), sum(item.stat().st_size for item in files), len(files))
            )
        usage = shutil.disk_usage(self.root)
        percent = round((usage.used / usage.total) * 100, 2)
        return {
            "categories": [asdict(value) for value in values],
            "disk": {"total": usage.total, "used": usage.used, "free": usage.free, "percent": percent},
            "warning_level": "EMERGENCY"
            if percent >= 90
            else "CRITICAL"
            if percent >= 80
            else "WARNING"
            if percent >= 70
            else "OK",
        }

    def cleanup_temporary_files(self, *, older_than_hours: int = 24) -> dict:
        temporary = self.categories["temporary"]
        self._assert_inside(temporary)
        if not temporary.exists():
            return {"removed": 0, "bytes_reclaimed": 0}
        cutoff = datetime.now(UTC) - timedelta(hours=max(1, older_than_hours))
        removed = bytes_reclaimed = 0
        for path in temporary.rglob("*"):
            if not path.is_file():
                continue
            # Keep the tracked directory sentinel so a routine cleanup does not
            # leave the repository dirty or remove the empty runtime directory.
            if path.name == ".gitkeep":
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if modified >= cutoff:
                continue
            size = path.stat().st_size
            path.unlink()
            removed += 1
            bytes_reclaimed += size
        return {"removed": removed, "bytes_reclaimed": bytes_reclaimed}

    def safe_path(self, category: str, relative_path: str) -> Path:
        if category not in self.categories:
            raise ValueError(f"unknown storage category: {category}")
        path = (self.categories[category] / relative_path).resolve()
        self._assert_inside(path)
        return path

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _assert_inside(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved != self.root and self.root not in resolved.parents:
            raise ValueError(f"path escapes Webnovel project root: {resolved}")
