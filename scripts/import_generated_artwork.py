"""Import inspected local originals through the production artwork pipeline."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from app.core.database import SessionLocal
from app.models import AuditLog, Chapter, ChapterImage, Novel
from app.services.illustrations import (
    ChapterIllustrationService,
    ExistingFileIllustrationProvider,
    IllustrationPlacement,
)
from sqlalchemy import select
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
    parser.add_argument(
        "manifest", nargs="?", help="Path inside the project, or '-' to read JSON from stdin"
    )
    parser.add_argument(
        "--scan-generated",
        type=Path,
        help="Import generated PNGs named NOVEL-CHAPTER-TYPE-ORDER.png from this project folder",
    )
    parser.add_argument(
        "--export-plan",
        type=int,
        action="append",
        help="Print the canonical generation plan for a novel as JSON (repeatable)",
    )
    arguments = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    if arguments.export_plan:
        entries = []
        with SessionLocal() as db:
            service = ChapterIllustrationService()
            for novel_id in arguments.export_plan:
                novel = db.get(Novel, novel_id)
                if not novel:
                    raise LookupError(f"novel not found: {novel_id}")
                profile = service.visual_profile(db, novel)
                chapters = db.scalars(
                    select(Chapter)
                    .where(Chapter.novel_id == novel.id)
                    .order_by(Chapter.chapter_order)
                ).all()
                for chapter in chapters:
                    for placement in service.placement_plan(chapter):
                        excerpt = service._excerpt(chapter, placement)
                        prompt = service.build_prompt(novel, chapter, placement, excerpt, profile)
                        prompt += (
                            " Render as a landscape 16:9 illustration. No text, caption, logo, "
                            "signature, or watermark. Depict one coherent scene only; do not create "
                            "a montage or reveal events beyond this excerpt."
                        )
                        entries.append(
                            {
                                "novel_id": novel.id,
                                "novel_title": novel.title,
                                "chapter_id": chapter.id,
                                "chapter_order": chapter.chapter_order,
                                "chapter_title": chapter.chapter_title,
                                "image_type": placement.image_type,
                                "placement_order": placement.placement_order,
                                "paragraph_anchor": placement.paragraph_anchor,
                                "animation_type": placement.animation_type,
                                "source_path": (
                                    "storage/temporary/generated-artwork/"
                                    f"{novel.id}-{chapter.id}-{placement.image_type}-"
                                    f"{placement.placement_order}.png"
                                ),
                                "alt_text": (
                                    f"Original {placement.image_type} illustration for "
                                    f"{chapter.chapter_title} from {novel.title}."
                                ),
                                "prompt": prompt,
                            }
                        )
        print(json.dumps(entries))
        return
    if arguments.scan_generated:
        scan_root = arguments.scan_generated.resolve()
        if scan_root != project_root and project_root not in scan_root.parents:
            raise ValueError("scan folder must be inside the Webnovel project")
        entries = []
        with SessionLocal() as db:
            service = ChapterIllustrationService()
            for source_path in sorted(scan_root.glob("*.png")):
                match = re.fullmatch(r"(\d+)-(\d+)-(hero|interval)-(\d+)\.png", source_path.name)
                if not match:
                    continue
                novel_id, chapter_id, image_type, placement_order = match.groups()
                chapter = db.get(Chapter, int(chapter_id))
                novel = db.get(Novel, int(novel_id))
                if not chapter or not novel or chapter.novel_id != novel.id:
                    raise LookupError(f"invalid generated-artwork filename: {source_path.name}")
                placement = next(
                    (
                        candidate
                        for candidate in service.placement_plan(chapter)
                        if candidate.image_type == image_type
                        and candidate.placement_order == int(placement_order)
                    ),
                    None,
                )
                if not placement:
                    raise ValueError(f"placement is not in canonical plan: {source_path.name}")
                existing = db.scalar(
                    select(ChapterImage).where(
                        ChapterImage.chapter_id == chapter.id,
                        ChapterImage.image_type == placement.image_type,
                        ChapterImage.placement_order == placement.placement_order,
                    )
                )
                if existing and existing.approved:
                    continue
                profile = service.visual_profile(db, novel)
                excerpt = service._excerpt(chapter, placement)
                prompt = service.build_prompt(novel, chapter, placement, excerpt, profile)
                prompt += (
                    " Render as a landscape 16:9 illustration. No text, caption, logo, "
                    "signature, or watermark."
                )
                entries.append(
                    {
                        "chapter_id": chapter.id,
                        "source_path": source_path.relative_to(project_root).as_posix(),
                        "image_type": placement.image_type,
                        "placement_order": placement.placement_order,
                        "paragraph_anchor": placement.paragraph_anchor,
                        "animation_type": placement.animation_type,
                        "alt_text": (
                            f"Original {placement.image_type} illustration for "
                            f"{chapter.chapter_title} from {novel.title}."
                        ),
                        "prompt": prompt,
                        "visual_profile": service._profile_dict(profile),
                    }
                )
        if not entries:
            raise ValueError("no generated artwork files found")
    elif arguments.manifest == "-":
        entries = json.load(sys.stdin)
    elif arguments.manifest:
        manifest_path = Path(arguments.manifest).resolve()
        if manifest_path != project_root and project_root not in manifest_path.parents:
            raise ValueError("manifest must be inside the Webnovel project")
        entries = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        parser.error("provide a manifest or --scan-generated")
    with SessionLocal() as db:
        image_ids = [import_entry(db, project_root, entry) for entry in entries]
    print(json.dumps({"imported": len(image_ids), "image_ids": image_ids, "approval_required": True}))


if __name__ == "__main__":
    main()
