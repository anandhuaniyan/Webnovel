from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import IllustrationMode
from app.models import Chapter, ChapterImage, Novel


@dataclass(frozen=True)
class IllustrationBrief:
    novel_title: str
    chapter_title: str
    canonical_excerpt: str
    source_hash: str
    alt_text: str


class IllustrationProvider(Protocol):
    def generate(self, brief: IllustrationBrief, output_path: Path) -> Path: ...


class DisabledIllustrationProvider:
    def generate(self, brief: IllustrationBrief, output_path: Path) -> Path:
        raise RuntimeError(
            "Chapter illustration generation is disabled. Configure and inject an approved provider."
        )


class ChapterIllustrationService:
    def __init__(self, provider: IllustrationProvider | None = None):
        self.settings = get_settings()
        self.provider = provider or DisabledIllustrationProvider()

    @staticmethod
    def should_generate(mode: str, chapter_order: int, *, ai_selected: bool = False) -> bool:
        selected = IllustrationMode(mode)
        if selected == IllustrationMode.NONE:
            return False
        if selected == IllustrationMode.ALL_CHAPTERS:
            return True
        if selected == IllustrationMode.EVERY_5_CHAPTERS:
            return chapter_order % 5 == 0
        if selected == IllustrationMode.EVERY_10_CHAPTERS:
            return chapter_order % 10 == 0
        if selected in {IllustrationMode.AI_SELECTED, IllustrationMode.IMPORTANT_CHAPTERS}:
            return ai_selected
        return False

    def generate(self, db: Session, novel: Novel, chapter: Chapter, *, alt_text: str) -> ChapterImage:
        if chapter.novel_id != novel.id:
            raise ValueError("chapter does not belong to novel")
        target_dir = (self.settings.storage_path / "chapter-images" / novel.slug).resolve()
        storage_root = self.settings.storage_path.resolve()
        if storage_root not in target_dir.parents:
            raise ValueError("illustration path escaped project storage")
        target_dir.mkdir(parents=True, exist_ok=True)
        brief = IllustrationBrief(
            novel_title=novel.title,
            chapter_title=chapter.chapter_title,
            canonical_excerpt=chapter.content_text[:4_000],
            source_hash=chapter.content_hash,
            alt_text=alt_text,
        )
        source = self.provider.generate(brief, target_dir / f"{chapter.chapter_slug}-source.png")
        output = target_dir / f"{chapter.chapter_slug}.webp"
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image.save(output, "WEBP", quality=84, method=6)
        record = ChapterImage(
            chapter_id=chapter.id,
            path=str(output.relative_to(self.settings.project_root)),
            alt_text=alt_text[:500],
            content_hash=hashlib.sha256(output.read_bytes()).hexdigest(),
            approved=False,
        )
        db.add(record)
        db.commit()
        return record
