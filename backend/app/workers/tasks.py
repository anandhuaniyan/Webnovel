from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select

from app.core.database import SessionLocal
from app.core.enums import ImportStatus
from app.models import Author, Genre, ImportJob, Novel, NovelGenre, Work
from app.services.covers import CoverBrief, CoverGenerationService
from app.services.discovery import DiscoveryService
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
