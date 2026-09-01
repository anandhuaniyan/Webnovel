"""Import inspected local originals through the production artwork pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.database import SessionLocal
from app.models import AuditLog, Chapter, Novel
from app.services.illustrations import (
    ChapterIllustrationService,
    ExistingFileIllustrationProvider,
    IllustrationPlacement,
)
from sqlalchemy.orm import Session

PROFILE_FIELDS = {
    "historical_period",
    "environments",
    "recurring_characters",
    "atmosphere",
    "illustration_style",
    "lighting_style",
    "color_palette",
    "visual_motifs",
    "prompt_constraints",
}


def import_entry(db: Session, project_root: Path, entry: dict) -> int:
    chapter = db.get(Chapter, int(entry["chapter_id"]))
    if not chapter:
        raise LookupError(f"chapter not found: {entry['chapter_id']}")
    novel = db.get(Novel, chapter.novel_id)
    if not novel:
        raise LookupError(f"novel not found for chapter: {chapter.id}")
    source_path = (project_root / entry["source_path"]).resolve()
    if source_path != project_root and project_root not in source_path.parents:
        raise ValueError(f"source path escapes project root: {source_path}")
    service = ChapterIllustrationService(ExistingFileIllustrationProvider(source_path))
    profile = service.visual_profile(db, novel)
    for name, value in entry.get("visual_profile", {}).items():
        if name not in PROFILE_FIELDS:
            raise ValueError(f"unknown visual profile field: {name}")
        setattr(profile, name, value)
    placement = IllustrationPlacement(
        image_type=entry["image_type"],
        placement_order=int(entry["placement_order"]),
        paragraph_anchor=entry.get("paragraph_anchor"),
        animation_type=entry.get("animation_type", "none"),
    )
    image = service.generate_placement(
        db,
        novel,
        chapter,
        placement,
        profile,
        alt_text=entry["alt_text"],
        prompt_override=entry["prompt"],
    )
    db.add(
        AuditLog(
            actor_type="LOCAL_IMAGEGEN",
            action="CHAPTER_ARTWORK_IMPORTED",
            entity_type="chapter_image",
            entity_id=str(image.id),
            details={
                "source_path": entry["source_path"],
                "provider": image.generation_provider,
                "model": image.generation_model,
                "approval_required": True,
            },
        )
    )
    db.commit()
    return image.id


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    arguments = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    manifest_path = arguments.manifest.resolve()
    if manifest_path != project_root and project_root not in manifest_path.parents:
        raise ValueError("manifest must be inside the Webnovel project")
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        image_ids = [import_entry(db, project_root, entry) for entry in entries]
    print(json.dumps({"imported": len(image_ids), "image_ids": image_ids, "approval_required": True}))


if __name__ == "__main__":
    main()
