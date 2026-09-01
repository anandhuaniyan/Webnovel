from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.core.enums import ImportStatus
from app.models import (
    Author,
    Chapter,
    ChapterImage,
    Genre,
    ImportJob,
    Novel,
    NovelGenre,
    QualityIssue,
    Work,
)
from app.services.covers import CoverBrief, CoverGenerationService
from app.services.discovery import DiscoveryService
from app.services.illustrations import ChapterIllustrationService
from app.services.ingestion import IngestionService
from app.services.rights import RightsEngine
from app.services.storage import StorageService
from app.workers.celery_app import celery_app


@celery_app.task(
    name="webnovel.discover", bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5
)
def discover(self, source_code: str, page: int = 1, limit: int = 20) -> dict:
    with SessionLocal() as db:
        result = DiscoveryService().discover(db, source_code, page=page, limit=limit)
    for job_id in result["job_ids"]:
        process_import.delay(job_id)
    result["queued_for_rights_screening"] = len(result["job_ids"])
    return result


@celery_app.task(
    name="webnovel.discover_item",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=5,
)
def discover_item(self, source_code: str, external_id: str) -> dict:
    with SessionLocal() as db:
        result = DiscoveryService().discover_item(db, source_code, external_id)
    if result["outcome"] == "created" and result["job_id"]:
        process_import.delay(result["job_id"])
    return result


@celery_app.task(
    name="webnovel.process_import", bind=True, autoretry_for=(Exception,), retry_backoff=True, max_retries=5
)
def process_import(self, job_id: int) -> dict:
    with SessionLocal() as db:
        return IngestionService().process(db, job_id)


@celery_app.task(
    name="webnovel.generate_cover",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def generate_cover(self, novel_id: int) -> dict:
    with SessionLocal() as db:
        novel = db.get(Novel, novel_id)
        if not novel:
            raise LookupError(f"novel not found: {novel_id}")
        author_name = db.scalar(select(Author.name).where(Author.id == novel.primary_author_id))
        genre_name = db.scalar(
            select(Genre.name)
            .join(NovelGenre, NovelGenre.genre_id == Genre.id)
            .where(NovelGenre.novel_id == novel.id)
            .order_by(NovelGenre.is_primary.desc(), Genre.name)
            .limit(1)
        )
        publication_year = db.scalar(select(Work.first_publication_year).where(Work.id == novel.work_id))
        brief = CoverBrief(
            title=novel.title,
            author=author_name or "Unknown author",
            genre=genre_name or novel.content_type.replace("_", " ").title(),
            setting=novel.setting,
            period=str(publication_year) if publication_year else None,
            themes=novel.themes,
            spoiler_free_description=novel.ai_synopsis
            or novel.description
            or "A faithful, non-spoiler visual interpretation of the reviewed work.",
        )
        images = CoverGenerationService().generate_for_novel(db, novel, brief)
        return {"novel_id": novel.id, "generated": len(images), "approval_required": True}


@celery_app.task(
    name="webnovel.generate_chapter_artwork",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    max_retries=3,
)
def generate_chapter_artwork(self, chapter_id: int) -> dict:
    with SessionLocal() as db:
        chapter = db.get(Chapter, chapter_id)
        if not chapter:
            raise LookupError(f"chapter not found: {chapter_id}")
        novel = db.get(Novel, chapter.novel_id)
        if not novel:
            raise LookupError(f"novel not found for chapter: {chapter_id}")
        try:
            images = ChapterIllustrationService().generate_for_chapter(db, novel, chapter)
        except Exception as exc:
            issue = db.scalar(
                select(QualityIssue).where(
                    QualityIssue.novel_id == novel.id,
                    QualityIssue.code == f"CHAPTER_ARTWORK_FAILED_{chapter.id}",
                    QualityIssue.resolved_at.is_(None),
                )
            )
            if issue:
                issue.message = str(exc)[:2_000]
            else:
                db.add(
                    QualityIssue(
                        novel_id=novel.id,
                        code=f"CHAPTER_ARTWORK_FAILED_{chapter.id}",
                        severity="WARNING",
                        message=str(exc)[:2_000],
                        blocking=False,
                    )
                )
            db.commit()
            raise
        for issue in db.scalars(
            select(QualityIssue).where(
                QualityIssue.novel_id == novel.id,
                QualityIssue.code == f"CHAPTER_ARTWORK_FAILED_{chapter.id}",
                QualityIssue.resolved_at.is_(None),
            )
        ).all():
            issue.resolved_at = datetime.now(UTC)
        db.commit()
        return {
            "novel_id": novel.id,
            "chapter_id": chapter.id,
            "generated": len(images),
            "approval_required": True,
        }


@celery_app.task(name="webnovel.generate_novel_artwork")
def generate_novel_artwork(novel_id: int, limit: int = 20) -> dict:
    with SessionLocal() as db:
        novel = db.get(Novel, novel_id)
        if not novel:
            raise LookupError(f"novel not found: {novel_id}")
        chapter_ids = db.scalars(
            select(Chapter.id)
            .where(Chapter.novel_id == novel.id)
            .order_by(Chapter.chapter_order)
            .limit(min(max(limit, 1), 500))
        ).all()
    queued = [generate_chapter_artwork.delay(chapter_id).id for chapter_id in chapter_ids]
    return {"novel_id": novel_id, "queued": len(queued), "task_ids": queued}


@celery_app.task(name="webnovel.retry_due_imports")
def retry_due_imports() -> dict:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        jobs = db.scalars(
            select(ImportJob.id)
            .where(
                ImportJob.status == ImportStatus.FAILED.value,
                or_(ImportJob.next_retry_at.is_(None), ImportJob.next_retry_at <= now),
                ImportJob.attempt_count < 10,
            )
            .limit(100)
        ).all()
    for job_id in jobs:
        process_import.delay(job_id)
    return {"queued": len(jobs)}


@celery_app.task(name="webnovel.rights_recheck")
def rights_recheck() -> dict:
    with SessionLocal() as db:
        return {"unpublished": RightsEngine().recheck_due_rights(db)}


@celery_app.task(name="webnovel.storage_metrics")
def storage_metrics() -> dict:
    return StorageService().metrics()


@celery_app.task(name="webnovel.cleanup_temporary_files")
def cleanup_temporary_files() -> dict:
    return StorageService().cleanup_temporary_files(older_than_hours=24)


@celery_app.task(name="webnovel.check_chapter_artwork")
def check_chapter_artwork() -> dict:
    storage = StorageService()
    missing = 0
    with SessionLocal() as db:
        for image in db.scalars(select(ChapterImage)).all():
            path = (storage.root / image.path).resolve()
            issue_code = f"CHAPTER_IMAGE_MISSING_{image.id}"
            issue = db.scalar(
                select(QualityIssue).where(
                    QualityIssue.code == issue_code,
                    QualityIssue.resolved_at.is_(None),
                )
            )
            present = (
                False
                if path != storage.root and storage.root not in path.parents
                else path.is_file()
            )
            if not present:
                missing += 1
                if issue:
                    issue.message = f"Artwork file is missing: {image.path}"
                else:
                    chapter = db.get(Chapter, image.chapter_id)
                    db.add(
                        QualityIssue(
                            novel_id=chapter.novel_id if chapter else None,
                            code=issue_code,
                            severity="ERROR",
                            message=f"Artwork file is missing: {image.path}",
                            blocking=True,
                        )
                    )
                image.approved = False
            elif issue:
                issue.resolved_at = datetime.now(UTC)
        db.commit()
    return {"checked": True, "missing": missing}
