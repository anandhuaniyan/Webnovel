from __future__ import annotations

import hashlib
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx
from bs4 import BeautifulSoup
from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import IllustrationMode
from app.models import Chapter, ChapterImage, Novel, NovelVisualProfile


@dataclass(frozen=True)
class IllustrationPlacement:
    image_type: str
    placement_order: int
    paragraph_anchor: int | None
    animation_type: str


@dataclass(frozen=True)
class IllustrationBrief:
    novel_title: str
    chapter_title: str
    canonical_excerpt: str
    source_hash: str
    alt_text: str
    image_type: str
    placement_order: int
    paragraph_anchor: int | None
    animation_type: str
    generation_prompt: str
    visual_profile: dict


class IllustrationProvider(Protocol):
    provider_name: str
    model_name: str | None

    def generate(self, brief: IllustrationBrief, output_path: Path) -> Path: ...


class DisabledIllustrationProvider:
    provider_name = "disabled"
    model_name = None

    def generate(self, brief: IllustrationBrief, output_path: Path) -> Path:
        raise RuntimeError(
            "Chapter illustration generation is disabled. Configure and inject an approved provider."
        )


class HttpIllustrationProvider:
    """Adapter for an explicitly configured image generation service."""

    provider_name = "http"
    model_name = None
    MAX_RESPONSE_BYTES = 25 * 1024 * 1024

    def __init__(self, endpoint: str, api_key: str):
        self.endpoint = endpoint
        self.api_key = api_key

    def generate(self, brief: IllustrationBrief, output_path: Path) -> Path:
        response = httpx.post(
            self.endpoint,
            json={"brief": asdict(brief), "format": "png", "width": 1600, "height": 900},
            headers={"Authorization": f"Bearer {self.api_key}"},
            timeout=180,
            follow_redirects=False,
        )
        response.raise_for_status()
        if not response.headers.get("content-type", "").lower().startswith("image/"):
            raise RuntimeError("configured illustration provider did not return an image")
        if not response.content or len(response.content) > self.MAX_RESPONSE_BYTES:
            raise RuntimeError("configured illustration provider returned an invalid image size")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        return output_path


class ExistingFileIllustrationProvider:
    """Imports an already generated, local original into the normal media pipeline."""

    provider_name = "built-in-imagegen-import"
    model_name = "gpt-image"

    def __init__(self, source_path: Path):
        self.source_path = source_path.resolve()

    def generate(self, brief: IllustrationBrief, output_path: Path) -> Path:
        if not self.source_path.is_file():
            raise FileNotFoundError(self.source_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.source_path, output_path)
        return output_path


class ChapterIllustrationService:
    HERO_SIZE = (1600, 900)
    INTERVAL_SIZE = (1400, 875)
    DEFAULT_CONSTRAINTS = [
        "original composition grounded only in the supplied canonical excerpt",
        "period-appropriate clothing, architecture, objects, and lighting",
        "no copied book art, film designs, television designs, or commercial artwork",
        "no imitation of a living artist",
        "no typography, captions, logos, signatures, or watermarks",
        "avoid spoilers beyond the supplied excerpt",
    ]

    def __init__(self, provider: IllustrationProvider | None = None):
        self.settings = get_settings()
        self.provider = provider or self._configured_provider()

    def _configured_provider(self) -> IllustrationProvider:
        if self.settings.ai_image_provider == "http":
            return HttpIllustrationProvider(
                self.settings.ai_image_endpoint,
                self.settings.ai_image_api_key,
            )
        return DisabledIllustrationProvider()

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

    @staticmethod
    def _paragraphs(chapter: Chapter) -> list[str]:
        soup = BeautifulSoup(chapter.content_html, "lxml")
        paragraphs = [node.get_text(" ", strip=True) for node in soup.select("p")]
        return [paragraph for paragraph in paragraphs if paragraph]

    @classmethod
    def placement_plan(cls, chapter: Chapter) -> list[IllustrationPlacement]:
        paragraphs = cls._paragraphs(chapter)
        count = len(paragraphs)
        interval_count = 0
        if chapter.word_count >= 12_000:
            interval_count = 4
        elif chapter.word_count >= 7_000:
            interval_count = 3
        elif chapter.word_count >= 3_000:
            interval_count = 2
        elif chapter.word_count >= 1_200:
            interval_count = 1
        plan = [IllustrationPlacement("hero", 0, None, cls._animation_for(chapter.content_text[:3_000]))]
        if count < 5:
            return plan
        for order in range(1, interval_count + 1):
            target = round(count * order / (interval_count + 1))
            lower = max(2, target - 2)
            upper = min(count - 2, target + 2)
            candidates = list(range(lower, upper + 1))
            anchor = min(
                candidates,
                key=lambda index: (
                    not paragraphs[index - 1].rstrip().endswith((".", "!", "?", "”", "’")),
                    len(paragraphs[index - 1]) < 80,
                    abs(index - target),
                ),
            )
            excerpt = " ".join(paragraphs[max(0, anchor - 2) : min(count, anchor + 2)])
            plan.append(
                IllustrationPlacement("interval", order, anchor, cls._animation_for(excerpt))
            )
        return plan

    @staticmethod
    def _animation_for(text: str) -> str:
        lowered = text.lower()
        water_matches = re.findall(r"\b(?:sea|ocean|water|waves?|river)\b", lowered)
        if len(water_matches) >= 2:
            return "water"
        if re.search(r"\b(?:rain|rainy|drizzle|drizzly|fog|mist|snow|clouds?)\b", lowered):
            return "drift"
        if re.search(r"\b(?:fire|flames?|candles?|lamps?|hearth)\b", lowered):
            return "light_flicker"
        return "slow_zoom"

    def visual_profile(self, db: Session, novel: Novel) -> NovelVisualProfile:
        profile = db.scalar(
            select(NovelVisualProfile).where(NovelVisualProfile.novel_id == novel.id)
        )
        if profile:
            return profile
        profile = NovelVisualProfile(
            novel_id=novel.id,
            environments=[novel.setting] if novel.setting else [],
            atmosphere=novel.themes,
            color_palette=["muted earth tones", "deep ink shadows", "warm highlights"],
            visual_motifs=[],
            prompt_constraints=list(self.DEFAULT_CONSTRAINTS),
        )
        db.add(profile)
        db.flush()
        return profile

    @staticmethod
    def _profile_dict(profile: NovelVisualProfile) -> dict:
        return {
            "historical_period": profile.historical_period,
            "environments": profile.environments,
            "recurring_characters": profile.recurring_characters,
            "atmosphere": profile.atmosphere,
            "illustration_style": profile.illustration_style,
            "lighting_style": profile.lighting_style,
            "color_palette": profile.color_palette,
            "visual_motifs": profile.visual_motifs,
            "prompt_constraints": profile.prompt_constraints,
        }

    @classmethod
    def _excerpt(cls, chapter: Chapter, placement: IllustrationPlacement) -> str:
        paragraphs = cls._paragraphs(chapter)
        if placement.paragraph_anchor is None or not paragraphs:
            return " ".join(paragraphs[:8])[:4_000] or chapter.content_text[:4_000]
        anchor = placement.paragraph_anchor
        return " ".join(paragraphs[max(0, anchor - 3) : anchor + 3])[:4_000]

    @classmethod
    def build_prompt(
        cls,
        novel: Novel,
        chapter: Chapter,
        placement: IllustrationPlacement,
        excerpt: str,
        profile: NovelVisualProfile,
    ) -> str:
        profile_data = cls._profile_dict(profile)
        profile_lines = "; ".join(
            f"{key.replace('_', ' ')}: {value}"
            for key, value in profile_data.items()
            if value and key != "prompt_constraints"
        )
        constraints = "; ".join(profile.prompt_constraints or cls.DEFAULT_CONSTRAINTS)
        purpose = (
            "wide cinematic chapter-opening illustration"
            if placement.image_type == "hero"
            else "wide editorial interval illustration at a natural scene boundary"
        )
        return (
            f"Create an original {purpose} for {novel.title}, chapter "
            f"{chapter.chapter_order}: {chapter.chapter_title}. Ground every visible detail in this "
            f"canonical excerpt: {excerpt}. Maintain this novel visual profile: {profile_lines}. "
            f"Composition should leave calm negative space and remain readable behind subtle "
            f"{placement.animation_type.replace('_', ' ')} motion. Constraints: {constraints}."
        )[:12_000]

    def generate_for_chapter(
        self,
        db: Session,
        novel: Novel,
        chapter: Chapter,
        *,
        placements: list[IllustrationPlacement] | None = None,
    ) -> list[ChapterImage]:
        if chapter.novel_id != novel.id:
            raise ValueError("chapter does not belong to novel")
        profile = self.visual_profile(db, novel)
        records = [
            self.generate_placement(db, novel, chapter, placement, profile)
            for placement in (placements or self.placement_plan(chapter))
        ]
        db.commit()
        return records

    def generate_placement(
        self,
        db: Session,
        novel: Novel,
        chapter: Chapter,
        placement: IllustrationPlacement,
        profile: NovelVisualProfile | None = None,
        *,
        alt_text: str | None = None,
        prompt_override: str | None = None,
    ) -> ChapterImage:
        if chapter.novel_id != novel.id:
            raise ValueError("chapter does not belong to novel")
        existing = db.scalar(
            select(ChapterImage).where(
                ChapterImage.chapter_id == chapter.id,
                ChapterImage.image_type == placement.image_type,
                ChapterImage.placement_order == placement.placement_order,
            )
        )
        if existing and existing.approved:
            return existing
        profile = profile or self.visual_profile(db, novel)
        excerpt = self._excerpt(chapter, placement)
        prompt = (
            prompt_override[:12_000]
            if prompt_override
            else self.build_prompt(novel, chapter, placement, excerpt, profile)
        )
        resolved_alt = (
            alt_text or f"Original illustration for {chapter.chapter_title} from {novel.title}."
        )[:500]
        target_dir = (
            self.settings.storage_path / "chapter-images" / novel.slug / chapter.chapter_slug
        ).resolve()
        storage_root = self.settings.storage_path.resolve()
        if storage_root not in target_dir.parents:
            raise ValueError("illustration path escaped project storage")
        target_dir.mkdir(parents=True, exist_ok=True)
        basename = f"{placement.image_type}-{placement.placement_order}"
        brief = IllustrationBrief(
            novel_title=novel.title,
            chapter_title=chapter.chapter_title,
            canonical_excerpt=excerpt,
            source_hash=chapter.content_hash,
            alt_text=resolved_alt,
            image_type=placement.image_type,
            placement_order=placement.placement_order,
            paragraph_anchor=placement.paragraph_anchor,
            animation_type=placement.animation_type,
            generation_prompt=prompt,
            visual_profile=self._profile_dict(profile),
        )
        source = self.provider.generate(brief, target_dir / f"{basename}-source.png")
        output = target_dir / f"{basename}.webp"
        size = self.HERO_SIZE if placement.image_type == "hero" else self.INTERVAL_SIZE
        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
            image.save(output, "WEBP", quality=84, method=6)
            width, height = image.size
        relative_path = str(output.relative_to(self.settings.project_root)).replace("\\", "/")
        record = existing or ChapterImage(
            chapter_id=chapter.id,
            image_type=placement.image_type,
            placement_order=placement.placement_order,
        )
        record.paragraph_anchor = placement.paragraph_anchor
        record.path = relative_path
        record.fallback_path = relative_path
        record.alt_text = resolved_alt
        record.generation_prompt = prompt
        record.generation_provider = self.provider.provider_name
        record.generation_model = self.provider.model_name
        record.generated_at = datetime.now(UTC)
        record.source_status = "ORIGINAL_GENERATED"
        record.width = width
        record.height = height
        record.mime_type = "image/webp"
        record.file_size = output.stat().st_size
        record.animation_type = placement.animation_type
        record.content_hash = hashlib.sha256(output.read_bytes()).hexdigest()
        record.prompt_metadata = {
            "source_hash": chapter.content_hash,
            "canonical_excerpt_hash": hashlib.sha256(excerpt.encode()).hexdigest(),
            "visual_profile": self._profile_dict(profile),
            "constraints": profile.prompt_constraints or self.DEFAULT_CONSTRAINTS,
        }
        record.approved = False
        db.add(record)
        db.flush()
        return record

    def generate(
        self,
        db: Session,
        novel: Novel,
        chapter: Chapter,
        *,
        alt_text: str,
    ) -> ChapterImage:
        """Backward-compatible single-hero entry point."""
        placement = self.placement_plan(chapter)[0]
        record = self.generate_placement(
            db,
            novel,
            chapter,
            placement,
            alt_text=alt_text,
        )
        db.commit()
        return record
