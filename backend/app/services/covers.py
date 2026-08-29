from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

import httpx
from PIL import Image, ImageOps
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Novel, NovelImage


@dataclass(frozen=True)
class CoverBrief:
    title: str
    author: str
    genre: str
    setting: str | None
    period: str | None
    themes: str | None
    spoiler_free_description: str


class CoverProvider(Protocol):
    def generate(self, brief: CoverBrief, output_path: Path) -> Path: ...


class DisabledCoverProvider:
    def generate(self, brief: CoverBrief, output_path: Path) -> Path:
        raise RuntimeError(
            "AI cover generation is disabled. Configure WEBNOVEL_AI_IMAGE_PROVIDER with an approved provider."
        )


class HttpCoverProvider:
    """Adapter for an explicitly configured image-generation service."""

    MAX_RESPONSE_BYTES = 25 * 1024 * 1024

    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint
        self.api_key = api_key

    def generate(self, brief: CoverBrief, output_path: Path) -> Path:
        response = httpx.post(
            self.endpoint,
            json={"brief": asdict(brief), "format": "png", "width": 1200, "height": 1800},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=180,
            follow_redirects=False,
        )
        response.raise_for_status()
        if not response.headers.get("content-type", "").lower().startswith("image/"):
            raise RuntimeError("configured cover provider did not return an image")
        if not response.content or len(response.content) > self.MAX_RESPONSE_BYTES:
            raise RuntimeError("configured cover provider returned an invalid image size")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return output_path


class CoverGenerationService:
    SIZES = {"portrait": (1200, 1800), "thumbnail": (400, 600), "open_graph": (1200, 630)}

    def __init__(self, provider: CoverProvider | None = None):
        self.settings = get_settings()
        self.provider = provider or self._configured_provider()
        self.cover_root = self.settings.storage_path / "covers"

    def _configured_provider(self) -> CoverProvider:
        if self.settings.ai_image_provider == "http":
            return HttpCoverProvider(
                self.settings.ai_image_endpoint,
                self.settings.ai_image_api_key,
            )
        return DisabledCoverProvider()

    def generate_variants(self, brief: CoverBrief, slug: str) -> dict[str, str]:
        target_dir = (self.cover_root / slug).resolve()
        if self.settings.storage_path.resolve() not in target_dir.parents:
            raise ValueError("cover path escaped project storage")
        target_dir.mkdir(parents=True, exist_ok=True)
        original = self.provider.generate(brief, target_dir / "source.png")
        results: dict[str, str] = {}
        with Image.open(original) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            for name, size in self.SIZES.items():
                image = ImageOps.fit(source, size, method=Image.Resampling.LANCZOS)
                output = target_dir / f"{name}.webp"
                image.save(output, "WEBP", quality=86, method=6)
                results[name] = str(output.relative_to(self.settings.project_root))
        return results

    def generate_for_novel(self, db: Session, novel: Novel, brief: CoverBrief) -> list[NovelImage]:
        variants = self.generate_variants(brief, novel.slug)
        db.execute(delete(NovelImage).where(NovelImage.novel_id == novel.id, NovelImage.approved.is_(False)))
        records: list[NovelImage] = []
        for image_type, relative_path in variants.items():
            path = self.settings.project_root / relative_path
            with Image.open(path) as image:
                width, height = image.size
            record = NovelImage(
                novel_id=novel.id,
                image_type=image_type,
                path=relative_path,
                width=width,
                height=height,
                mime_type="image/webp",
                content_hash=self.content_hash(path),
                prompt_metadata={
                    "title": brief.title,
                    "author": brief.author,
                    "genre": brief.genre,
                    "setting": brief.setting,
                    "period": brief.period,
                    "themes": brief.themes,
                    "description": brief.spoiler_free_description,
                    "constraints": [
                        "original composition",
                        "no copied covers, adaptations, or commercial artwork",
                        "no imitation of living artists",
                    ],
                },
                approved=False,
            )
            db.add(record)
            records.append(record)
        db.commit()
        return records

    @staticmethod
    def content_hash(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()
