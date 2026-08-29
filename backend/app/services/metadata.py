from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Chapter, Novel


@dataclass(frozen=True)
class GroundedMetadata:
    synopsis: str
    description: str
    themes: str
    setting: str
    character_guide: str
    reading_difficulty: str
    literary_context: str
    source_hashes: tuple[str, ...]


class MetadataProvider(Protocol):
    def enrich(self, *, title: str, canonical_excerpts: tuple[dict, ...]) -> GroundedMetadata: ...


class DisabledMetadataProvider:
    def enrich(self, *, title: str, canonical_excerpts: tuple[dict, ...]) -> GroundedMetadata:
        raise RuntimeError(
            "AI metadata enrichment is disabled. Configure and inject an approved grounded provider."
        )


class GroundedMetadataService:
    """Stores supplementary metadata without ever changing canonical chapters."""

    def __init__(self, provider: MetadataProvider | None = None):
        self.settings = get_settings()
        self.provider = provider or DisabledMetadataProvider()

    def enrich(self, db: Session, novel: Novel) -> GroundedMetadata:
        chapters = db.scalars(
            select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.chapter_order)
        ).all()
        if not chapters:
            raise RuntimeError("metadata enrichment requires canonical chapters")
        excerpts = tuple(
            {
                "chapter_order": chapter.chapter_order,
                "chapter_title": chapter.chapter_title,
                "content_hash": chapter.content_hash,
                "excerpt": chapter.content_text[:8_000],
            }
            for chapter in chapters
        )
        result = self.provider.enrich(title=novel.title, canonical_excerpts=excerpts)
        canonical_hashes = {chapter.content_hash for chapter in chapters}
        if not result.source_hashes or not set(result.source_hashes).issubset(canonical_hashes):
            raise ValueError("metadata provider did not cite canonical chapter hashes")
        for value in (
            result.synopsis,
            result.description,
            result.themes,
            result.setting,
            result.character_guide,
            result.reading_difficulty,
            result.literary_context,
        ):
            if not value.strip():
                raise ValueError("metadata provider returned an empty required field")
        novel.ai_synopsis = result.synopsis
        novel.description = result.description
        novel.themes = result.themes
        novel.setting = result.setting
        novel.character_guide = result.character_guide
        novel.reading_difficulty = result.reading_difficulty
        novel.literary_context = result.literary_context
        db.commit()
        return result
