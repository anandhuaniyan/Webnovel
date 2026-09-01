from __future__ import annotations

import json
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.enums import (
    APPROVED_RIGHTS_STATUSES,
    ImportStatus,
    MonetizationStatus,
    RightsStatus,
    TakedownStatus,
)
from app.core.security import require_admin_key
from app.models import (
    AuditLog,
    Chapter,
    ChapterImage,
    ContactRequest,
    ImportJob,
    Novel,
    NovelImage,
    QualityIssue,
    Review,
    RightsEvidence,
    RightsRecord,
    RightsReviewer,
    Source,
    SourceItem,
    TakedownRequest,
    Work,
)
from app.services.deduplication import DeduplicationService
from app.services.monetization import MonetizationService
from app.services.rights import RightsEngine
from app.services.storage import StorageService
from app.workers.celery_app import celery_app
from app.workers.tasks import (
    discover,
    discover_item,
    generate_cover,
    process_import,
)
from app.workers.tasks import (
    generate_chapter_artwork as generate_chapter_artwork_task,
)
from app.workers.tasks import (
    generate_novel_artwork as generate_novel_artwork_task,
)

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class RightsApproval(BaseModel):
    status: str
    licence_name: str | None = None
    licence_version: str | None = None
    licence_url: str | None = None
    attribution_text: str | None = None
    verification_method: str = Field(min_length=10, max_length=255)
    reviewer_id: int = Field(gt=0)
    evidence_url: str | None = None
    evidence_description: str = Field(min_length=20, max_length=5000)
    review_interval_days: int = Field(default=365, ge=30, le=3650)


class RightsResearchUpdate(BaseModel):
    research_method: str = Field(min_length=5, max_length=120)
    research_provider: str = Field(min_length=2, max_length=120)
    research_summary: str = Field(min_length=40, max_length=10_000)
    evidence_url: str | None = Field(default=None, max_length=1500)
    evidence_description: str = Field(min_length=20, max_length=5000)


class RightsReviewerCreate(BaseModel):
    display_name: str = Field(min_length=2, max_length=255)
    reviewer_type: str = Field(default="INTERNAL", pattern="^(INTERNAL|EXTERNAL)$")


class RightsReviewAction(BaseModel):
    reviewer_id: int = Field(gt=0)
    verification_method: str = Field(min_length=10, max_length=255)
    evidence_url: str | None = Field(default=None, max_length=1500)
    evidence_description: str = Field(min_length=20, max_length=5000)


class AdminAction(BaseModel):
    action: str = Field(
        pattern="^(publish|republish|unpublish|reject|disable_ads|enable_ads|reprocess|reprocess_chapters|regenerate_cover|ready_to_publish)$"
    )
    reason: str = Field(min_length=5, max_length=2000)


class TakedownAction(BaseModel):
    status: str
    resolution: str = Field(min_length=5, max_length=10_000)


class ContactAction(BaseModel):
    status: str = Field(pattern="^(RECEIVED|REVIEWING|RESOLVED)$")
    resolution: str = Field(min_length=5, max_length=10_000)


class MergeAction(BaseModel):
    target_novel_id: int = Field(gt=0)
    reason: str = Field(min_length=10, max_length=2000)


class ModerationAction(BaseModel):
    approved: bool
    reason: str = Field(min_length=5, max_length=2000)


class ArtworkGenerationAction(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)
    chapter_limit: int = Field(default=100, ge=1, le=500)


def _service_status() -> dict:
    redis_status = "unavailable"
    workers: dict = {}
    with suppress(Exception):
        redis_client = Redis.from_url(get_settings().redis_url, socket_timeout=0.4)
        redis_status = "healthy" if redis_client.ping() else "unavailable"
        redis_client.close()
    with suppress(Exception):
        workers = celery_app.control.inspect(timeout=0.5).ping() or {}
    return {
        "database": "healthy",
        "redis": redis_status,
        "workers": {"status": "healthy" if workers else "unavailable", "active": len(workers)},
    }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    def count(model, *filters) -> int:
        return db.scalar(select(func.count(model.id)).where(*filters)) or 0

    return {
        "catalogue": {
            "works": count(Novel),
            "published": count(Novel, Novel.published.is_(True)),
            "staged": count(Novel, Novel.published.is_(False), Novel.content_type != "NON_TARGET"),
            "rejected_non_target": count(Novel, Novel.content_type == "NON_TARGET"),
            "rights_review": count(
                Novel,
                Novel.content_type != "NON_TARGET",
                Novel.rights_status.in_(
                    [
                        RightsStatus.RESEARCHING.value,
                        RightsStatus.UNVERIFIED.value,
                        RightsStatus.NEEDS_LEGAL_REVIEW.value,
                    ]
                ),
            ),
            "ads_eligible": count(Novel, Novel.ads_eligible.is_(True)),
        },
        "imports": {
            status.value: count(ImportJob, ImportJob.status == status.value) for status in ImportStatus
        },
        "quality": {
            "blocking": count(
                QualityIssue, QualityIssue.blocking.is_(True), QualityIssue.resolved_at.is_(None)
            ),
            "open": count(QualityIssue, QualityIssue.resolved_at.is_(None)),
            "incomplete_novels": count(
                Novel,
                Novel.completeness_status.in_(["INCOMPLETE", "POSSIBLY_INCOMPLETE", "UNKNOWN"]),
            ),
            "artwork_failures": count(
                QualityIssue,
                or_(
                    QualityIssue.code.like("CHAPTER_ARTWORK_FAILED_%"),
                    QualityIssue.code.like("CHAPTER_IMAGE_MISSING_%"),
                ),
                QualityIssue.resolved_at.is_(None),
            ),
        },
        "media": {
            "covers_awaiting_approval": count(NovelImage, NovelImage.approved.is_(False)),
            "published_without_cover": count(Novel, Novel.published.is_(True), Novel.cover_path.is_(None)),
            "chapter_artwork_awaiting_approval": count(
                ChapterImage, ChapterImage.approved.is_(False)
            ),
            "published_chapters_without_artwork": db.scalar(
                select(func.count(Chapter.id))
                .join(Novel, Novel.id == Chapter.novel_id)
                .where(
                    Novel.published.is_(True),
                    ~exists(
                        select(ChapterImage.id).where(
                            ChapterImage.chapter_id == Chapter.id,
                            ChapterImage.approved.is_(True),
                        )
                    ),
                )
            )
            or 0,
        },
        "takedowns": {
            "open": count(
                TakedownRequest,
                TakedownRequest.status.in_(
                    [
                        TakedownStatus.RECEIVED.value,
                        TakedownStatus.REVIEWING.value,
                        TakedownStatus.TEMPORARILY_DISABLED.value,
                    ]
                ),
            )
        },
        "contacts": {
            "open": count(
                ContactRequest,
                ContactRequest.status.in_(["RECEIVED", "REVIEWING"]),
            )
        },
        "storage": StorageService().metrics(),
        "services": _service_status(),
        "adsense_readiness": MonetizationService().readiness_report(db),
    }


@router.get("/import-jobs")
def import_jobs(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
) -> list[dict]:
    statement = select(ImportJob).order_by(ImportJob.updated_at.desc()).limit(limit)
    if status:
        statement = statement.where(ImportJob.status == status)
    return [
        {
            "id": job.id,
            "source_item_id": job.source_item_id,
            "novel_id": job.novel_id,
            "status": job.status,
            "checkpoint": job.checkpoint,
            "attempt_count": job.attempt_count,
            "error": job.error,
            "next_retry_at": job.next_retry_at,
            "updated_at": job.updated_at,
        }
        for job in db.scalars(statement).all()
    ]


@router.post("/discovery/{source_code}", status_code=202)
def start_discovery(source_code: str, page: int = 1, limit: int = Query(default=20, ge=1, le=100)) -> dict:
    if source_code not in {"gutenberg", "standard_ebooks", "wikisource"}:
        raise HTTPException(status_code=400, detail="Unsupported source")
    task = discover.delay(source_code, page, limit)
    return {"task_id": task.id, "source": source_code, "page": page, "limit": limit}


@router.post("/discovery/{source_code}/items/{external_id}", status_code=202)
def start_item_discovery(source_code: str, external_id: str) -> dict:
    if source_code not in {"gutenberg", "standard_ebooks", "wikisource"}:
        raise HTTPException(status_code=400, detail="Unsupported source")
    task = discover_item.delay(source_code, external_id)
    return {"task_id": task.id, "source": source_code, "external_id": external_id}


@router.post("/import-jobs/{job_id}/run", status_code=202)
def run_import(job_id: int, db: Session = Depends(get_db)) -> dict:
    if not db.get(ImportJob, job_id):
        raise HTTPException(status_code=404, detail="Import job not found")
    task = process_import.delay(job_id)
    return {"task_id": task.id, "job_id": job_id}


@router.get("/rights-queue")
def rights_queue(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(RightsRecord, Novel)
        .join(Novel, Novel.work_id == RightsRecord.work_id)
        .where(
            Novel.content_type != "NON_TARGET",
            RightsRecord.status.not_in([status.value for status in APPROVED_RIGHTS_STATUSES]),
        )
        .order_by(RightsRecord.updated_at)
        .limit(limit)
    ).all()
    result = []
    for record, novel in rows:
        reviewer = db.get(RightsReviewer, record.reviewer_id) if record.reviewer_id else None
        source_row = db.execute(
            select(SourceItem, Source)
            .join(Source, Source.id == SourceItem.source_id)
            .where(SourceItem.edition_id == record.edition_id)
            .limit(1)
        ).first()
        source_item, source = source_row if source_row else (None, None)
        evidence = db.scalars(
            select(RightsEvidence)
            .where(RightsEvidence.rights_record_id == record.id)
            .order_by(RightsEvidence.captured_at)
        ).all()
        result.append({
            "rights_record_id": record.id,
            "novel_id": novel.id,
            "edition_id": record.edition_id,
            "title": novel.title,
            "status": record.status,
            "jurisdiction": record.jurisdiction,
            "licence_claim": record.licence_name,
            "licence_url": record.licence_url,
            "notes": record.notes,
            "review_reference": record.review_reference,
            "reviewer_visibility": record.reviewer_visibility,
            "research_method": record.research_method,
            "research_provider": record.research_provider,
            "research_summary": record.research_summary,
            "research_completed_at": record.research_completed_at,
            "human_review_required": record.human_review_required,
            "human_review_status": record.human_review_status,
            "human_reviewer": (
                {"id": reviewer.id, "display_name": reviewer.display_name, "type": reviewer.reviewer_type}
                if reviewer else None
            ),
            "human_verified_at": record.verified_at,
            "verification_method": record.verification_method,
            "source": (
                {"name": source.name, "code": source.code, "external_id": source_item.external_id,
                 "url": source_item.source_url, "source_hash": source_item.source_hash}
                if source_item and source else None
            ),
            "evidence": [
                {"type": item.evidence_type, "source_url": item.source_url,
                 "local_path": item.local_path, "description": item.description,
                 "content_hash": item.content_hash, "captured_at": item.captured_at}
                for item in evidence
            ],
        })
    return result


@router.get("/rights-reviewers")
def rights_reviewers(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {"id": reviewer.id, "display_name": reviewer.display_name,
         "reviewer_type": reviewer.reviewer_type, "active": reviewer.active}
        for reviewer in db.scalars(select(RightsReviewer).order_by(RightsReviewer.display_name)).all()
    ]


@router.get("/rights/{record_id}")
def rights_record_detail(record_id: int, db: Session = Depends(get_db)) -> dict:
    record = db.get(RightsRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Rights record not found")
    reviewer = db.get(RightsReviewer, record.reviewer_id) if record.reviewer_id else None
    evidence = db.scalars(
        select(RightsEvidence)
        .where(RightsEvidence.rights_record_id == record.id)
        .order_by(RightsEvidence.captured_at)
    ).all()
    return {
        "rights_record_id": record.id,
        "status": record.status,
        "jurisdiction": record.jurisdiction,
        "review_reference": record.review_reference,
        "research_method": record.research_method,
        "research_provider": record.research_provider,
        "research_summary": record.research_summary,
        "research_completed_at": record.research_completed_at,
        "human_review_required": record.human_review_required,
        "human_review_status": record.human_review_status,
        "human_reviewer": (
            {"id": reviewer.id, "display_name": reviewer.display_name,
             "reviewer_type": reviewer.reviewer_type}
            if reviewer else (
                {"id": None, "display_name": record.verified_by, "reviewer_type": "LEGACY"}
                if record.verified_by else None
            )
        ),
        "human_verified_at": record.verified_at,
        "verification_method": record.verification_method,
        "reviewer_visibility": record.reviewer_visibility,
        "next_review_at": record.next_review_at,
        "notes": record.notes,
        "evidence": [
            {"type": item.evidence_type, "source_url": item.source_url,
             "local_path": item.local_path, "description": item.description,
             "content_hash": item.content_hash, "captured_at": item.captured_at}
            for item in evidence
        ],
    }


@router.post("/rights-reviewers", status_code=201)
def create_rights_reviewer(payload: RightsReviewerCreate, db: Session = Depends(get_db)) -> dict:
    reviewer = RightsReviewer(
        display_name=payload.display_name.strip(),
        reviewer_type=payload.reviewer_type,
        active=True,
    )
    db.add(reviewer)
    db.commit()
    db.refresh(reviewer)
    return {"id": reviewer.id, "display_name": reviewer.display_name,
            "reviewer_type": reviewer.reviewer_type, "active": reviewer.active}


@router.post("/rights/{record_id}/research")
def attach_rights_research(
    record_id: int, payload: RightsResearchUpdate, db: Session = Depends(get_db)
) -> dict:
    record = db.get(RightsRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Rights record not found")
    completed_at = datetime.now(UTC)
    record.research_method = payload.research_method
    record.research_provider = payload.research_provider
    record.research_summary = payload.research_summary
    record.research_completed_at = completed_at
    record.human_review_status = "PENDING"
    record.manual_approval = False
    record.reviewer_id = None
    record.verified_at = None
    record.next_review_at = None
    if not record.review_reference:
        record.review_reference = f"RIGHTS-{completed_at.year}-{record.id:05d}"
    db.add(
        RightsEvidence(
            rights_record_id=record.id,
            evidence_type="AI_ASSISTED_COPYRIGHT_RESEARCH",
            source_url=payload.evidence_url,
            description=payload.evidence_description,
        )
    )
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="RIGHTS_RESEARCH_RECORDED",
            entity_type="rights_record",
            entity_id=str(record.id),
            details={"review_reference": record.review_reference,
                     "research_method": record.research_method,
                     "research_provider": record.research_provider},
        )
    )
    db.commit()
    return {"recorded": True, "review_reference": record.review_reference,
            "research_completed_at": completed_at, "human_review_status": "PENDING"}


def _active_reviewer(db: Session, reviewer_id: int) -> RightsReviewer:
    reviewer = db.get(RightsReviewer, reviewer_id)
    if not reviewer or not reviewer.active:
        raise HTTPException(status_code=400, detail="An active private rights reviewer is required")
    return reviewer


@router.post("/rights/{record_id}/approve")
def approve_rights(record_id: int, payload: RightsApproval, db: Session = Depends(get_db)) -> dict:
    try:
        rights_status = RightsStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown rights status") from exc
    if rights_status not in APPROVED_RIGHTS_STATUSES:
        raise HTTPException(status_code=400, detail="Approval endpoint requires an approved status")
    record = db.get(RightsRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Rights record not found")
    reviewer = _active_reviewer(db, payload.reviewer_id)
    novel = db.scalar(select(Novel).where(Novel.work_id == record.work_id))
    if novel and novel.published and novel.edition_id != record.edition_id:
        raise HTTPException(
            status_code=409,
            detail="An alternate edition cannot replace a published edition without first unpublishing it.",
        )
    record.status = rights_status.value
    record.licence_name = payload.licence_name
    record.licence_version = payload.licence_version
    record.licence_url = payload.licence_url
    record.attribution_text = payload.attribution_text
    record.verification_method = payload.verification_method
    record.reviewer_id = reviewer.id
    record.verified_by = None
    record.verified_at = datetime.now(UTC)
    record.next_review_at = record.verified_at + timedelta(days=payload.review_interval_days)
    record.manual_approval = True
    record.human_review_required = True
    record.human_review_status = "APPROVED"
    record.reviewer_visibility = "PRIVATE"
    if not record.review_reference:
        record.review_reference = f"RIGHTS-{record.verified_at.year}-{record.id:05d}"

    evidence_root = StorageService().safe_path("rights_evidence", f"manual/{record.id}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / f"approval-{int(record.verified_at.timestamp())}.json"
    evidence_path.write_text(
        json.dumps(
            {
                "source_url": payload.evidence_url,
                "description": payload.evidence_description,
                "reviewer_id": reviewer.id,
                "review_reference": record.review_reference,
                "verified_at": record.verified_at.isoformat(),
                "jurisdiction": record.jurisdiction,
                "status": rights_status.value,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    db.add(
        RightsEvidence(
            rights_record_id=record.id,
            evidence_type="INDEPENDENT_MANUAL_REVIEW",
            source_url=payload.evidence_url,
            local_path=str(evidence_path.relative_to(StorageService().root)),
            description=payload.evidence_description,
            content_hash=StorageService.sha256(evidence_path),
        )
    )
    queued_job = None
    if novel:
        novel.edition_id = record.edition_id
        novel.rights_status = rights_status.value
        job = db.scalar(
            select(ImportJob)
            .join(SourceItem, SourceItem.id == ImportJob.source_item_id)
            .where(SourceItem.edition_id == record.edition_id)
            .order_by(ImportJob.id.desc())
        )
        if job and job.status == ImportStatus.RIGHTS_CHECK.value:
            job.status = ImportStatus.RIGHTS_APPROVED.value
            job.checkpoint = "VERIFY_RIGHTS"
            queued_job = job
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="RIGHTS_APPROVED",
            entity_type="rights_record",
            entity_id=str(record.id),
            details={"review_reference": record.review_reference, "reviewer_id": reviewer.id,
                     "status": rights_status.value, "verification_method": payload.verification_method},
        )
    )
    db.commit()
    task = process_import.delay(queued_job.id) if queued_job else None
    return {"approved": True, "status": record.status, "review_reference": record.review_reference,
            "next_review_at": record.next_review_at, "pipeline_task_id": task.id if task else None}


@router.post("/rights/{record_id}/needs-legal-review")
def needs_legal_review(
    record_id: int, payload: RightsReviewAction, db: Session = Depends(get_db)
) -> dict:
    record = db.get(RightsRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Rights record not found")
    reviewer = _active_reviewer(db, payload.reviewer_id)
    record.status = RightsStatus.NEEDS_LEGAL_REVIEW.value
    record.human_review_status = "NEEDS_LEGAL_REVIEW"
    record.manual_approval = False
    record.reviewer_id = reviewer.id
    record.verified_by = None
    record.verification_method = payload.verification_method
    record.verified_at = datetime.now(UTC)
    record.next_review_at = None
    record.reviewer_visibility = "PRIVATE"
    db.add(RightsEvidence(rights_record_id=record.id, evidence_type="HUMAN_REVIEW_NEEDS_LEGAL",
                          source_url=payload.evidence_url, description=payload.evidence_description))
    db.add(AuditLog(actor_type="ADMIN_KEY", action="RIGHTS_NEEDS_LEGAL_REVIEW",
                    entity_type="rights_record", entity_id=str(record.id),
                    details={"review_reference": record.review_reference, "reviewer_id": reviewer.id}))
    db.commit()
    return {"needs_legal_review": True, "status": record.status,
            "review_reference": record.review_reference}


@router.post("/rights/{record_id}/reject")
def reject_rights(record_id: int, payload: RightsReviewAction, db: Session = Depends(get_db)) -> dict:
    record = db.get(RightsRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Rights record not found")
    reviewer = _active_reviewer(db, payload.reviewer_id)
    record.status = RightsStatus.RESTRICTED.value
    record.manual_approval = False
    record.human_review_status = "REJECTED"
    record.reviewer_id = reviewer.id
    record.verified_by = None
    record.verification_method = payload.verification_method
    record.verified_at = datetime.now(UTC)
    record.next_review_at = None
    record.reviewer_visibility = "PRIVATE"
    novel = db.scalar(select(Novel).where(Novel.edition_id == record.edition_id))
    if novel:
        novel.published = False
        novel.ads_eligible = False
        novel.rights_status = RightsStatus.RESTRICTED.value
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="RIGHTS_REJECTED",
            entity_type="rights_record",
            entity_id=str(record.id),
            details={"review_reference": record.review_reference, "reviewer_id": reviewer.id},
        )
    )
    db.add(RightsEvidence(rights_record_id=record.id, evidence_type="HUMAN_REVIEW_REJECTED",
                          source_url=payload.evidence_url, description=payload.evidence_description))
    db.commit()
    return {"rejected": True, "status": record.status}


@router.get("/cover-queue")
def cover_queue(db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(NovelImage, Novel)
        .join(Novel, Novel.id == NovelImage.novel_id)
        .where(NovelImage.approved.is_(False))
        .order_by(NovelImage.created_at)
        .limit(200)
    ).all()
    return [
        {
            "image_id": image.id,
            "novel_id": novel.id,
            "title": novel.title,
            "type": image.image_type,
            "path": image.path,
        }
        for image, novel in rows
    ]


@router.post("/novel-images/{image_id}/moderate")
def moderate_cover(image_id: int, payload: ModerationAction, db: Session = Depends(get_db)) -> dict:
    image = db.get(NovelImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    image.approved = payload.approved
    novel = db.get(Novel, image.novel_id)
    if novel and payload.approved:
        if image.image_type == "portrait":
            novel.cover_path = image.path
        elif image.image_type == "thumbnail":
            novel.thumbnail_path = image.path
        elif image.image_type == "open_graph":
            novel.og_image_path = image.path
        approved_types = set(
            db.scalars(
                select(NovelImage.image_type).where(
                    NovelImage.novel_id == novel.id,
                    NovelImage.approved.is_(True),
                )
            ).all()
        )
        if {"portrait", "thumbnail", "open_graph"} <= approved_types:
            job = db.scalar(
                select(ImportJob).where(ImportJob.novel_id == novel.id).order_by(ImportJob.id.desc())
            )
            if job and job.status == ImportStatus.READY_FOR_COVER.value:
                job.status = ImportStatus.READY_TO_PUBLISH.value
                job.checkpoint = "FINAL_REVIEW"
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="COVER_APPROVED" if payload.approved else "COVER_REJECTED",
            entity_type="novel_image",
            entity_id=str(image.id),
            details={"reason": payload.reason},
        )
    )
    db.commit()
    return {"image_id": image.id, "approved": image.approved}


@router.get("/artwork-queue")
def artwork_queue(limit: int = Query(default=100, ge=1, le=500), db: Session = Depends(get_db)) -> dict:
    pending_rows = db.execute(
        select(ChapterImage, Chapter, Novel)
        .join(Chapter, Chapter.id == ChapterImage.chapter_id)
        .join(Novel, Novel.id == Chapter.novel_id)
        .where(ChapterImage.approved.is_(False))
        .order_by(ChapterImage.created_at)
        .limit(limit)
    ).all()
    missing_rows = db.execute(
        select(Chapter, Novel)
        .join(Novel, Novel.id == Chapter.novel_id)
        .where(
            Novel.published.is_(True),
            ~exists(
                select(ChapterImage.id).where(
                    ChapterImage.chapter_id == Chapter.id,
                    ChapterImage.approved.is_(True),
                )
            ),
        )
        .order_by(Novel.title, Chapter.chapter_order)
        .limit(limit)
    ).all()
    return {
        "pending": [
            {
                "image_id": image.id,
                "chapter_id": chapter.id,
                "novel_id": novel.id,
                "novel_title": novel.title,
                "chapter_title": chapter.chapter_title,
                "image_type": image.image_type,
                "placement_order": image.placement_order,
                "path": image.path,
                "url": f"/media/{image.path.replace('storage/', '', 1)}",
                "animation_type": image.animation_type,
                "generation_provider": image.generation_provider,
                "generation_prompt": image.generation_prompt,
                "alt_text": image.alt_text,
            }
            for image, chapter, novel in pending_rows
        ],
        "missing": [
            {
                "chapter_id": chapter.id,
                "novel_id": novel.id,
                "novel_title": novel.title,
                "chapter_title": chapter.chapter_title,
                "chapter_order": chapter.chapter_order,
            }
            for chapter, novel in missing_rows
        ],
    }


@router.post("/chapters/{chapter_id}/artwork/generate", status_code=202)
def generate_chapter_artwork(
    chapter_id: int,
    payload: ArtworkGenerationAction,
    db: Session = Depends(get_db),
) -> dict:
    chapter = db.get(Chapter, chapter_id)
    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    if get_settings().ai_image_provider != "http":
        raise HTTPException(
            status_code=409,
            detail="Chapter artwork generation is disabled until the approved HTTP provider is configured.",
        )
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="CHAPTER_ARTWORK_QUEUED",
            entity_type="chapter",
            entity_id=str(chapter.id),
            details={"reason": payload.reason},
        )
    )
    db.commit()
    task = generate_chapter_artwork_task.delay(chapter.id)
    return {"chapter_id": chapter.id, "task_id": task.id, "approval_required": True}


@router.post("/novels/{novel_id}/artwork/generate", status_code=202)
def generate_novel_artwork(
    novel_id: int,
    payload: ArtworkGenerationAction,
    db: Session = Depends(get_db),
) -> dict:
    novel = db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    if get_settings().ai_image_provider != "http":
        raise HTTPException(
            status_code=409,
            detail="Chapter artwork generation is disabled until the approved HTTP provider is configured.",
        )
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="NOVEL_ARTWORK_QUEUED",
            entity_type="novel",
            entity_id=str(novel.id),
            details={"reason": payload.reason, "chapter_limit": payload.chapter_limit},
        )
    )
    db.commit()
    task = generate_novel_artwork_task.delay(novel.id, payload.chapter_limit)
    return {"novel_id": novel.id, "task_id": task.id, "approval_required": True}


@router.post("/chapter-images/{image_id}/moderate")
def moderate_chapter_artwork(
    image_id: int,
    payload: ModerationAction,
    db: Session = Depends(get_db),
) -> dict:
    image = db.get(ChapterImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Chapter artwork not found")
    image.approved = payload.approved
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="CHAPTER_ARTWORK_APPROVED" if payload.approved else "CHAPTER_ARTWORK_REJECTED",
            entity_type="chapter_image",
            entity_id=str(image.id),
            details={"reason": payload.reason},
        )
    )
    db.commit()
    return {"image_id": image.id, "approved": image.approved}


@router.get("/reviews")
def review_queue(db: Session = Depends(get_db)) -> list[dict]:
    reviews = db.scalars(
        select(Review).where(Review.approved.is_(False)).order_by(Review.created_at).limit(200)
    ).all()
    return [
        {
            "id": review.id,
            "novel_id": review.novel_id,
            "title": review.title,
            "body": review.body,
            "contains_spoilers": review.contains_spoilers,
        }
        for review in reviews
    ]


@router.post("/reviews/{review_id}/moderate")
def moderate_review(review_id: int, payload: ModerationAction, db: Session = Depends(get_db)) -> dict:
    review = db.get(Review, review_id)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review.approved = payload.approved
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="REVIEW_APPROVED" if payload.approved else "REVIEW_REJECTED",
            entity_type="review",
            entity_id=str(review.id),
            details={"reason": payload.reason},
        )
    )
    db.commit()
    return {"id": review.id, "approved": review.approved}


@router.get("/seo-status")
def seo_status(db: Session = Depends(get_db)) -> dict:
    published = db.scalar(select(func.count(Novel.id)).where(Novel.published.is_(True))) or 0
    missing_title = (
        db.scalar(select(func.count(Novel.id)).where(Novel.published.is_(True), Novel.seo_title.is_(None)))
        or 0
    )
    missing_description = (
        db.scalar(
            select(func.count(Novel.id)).where(Novel.published.is_(True), Novel.seo_description.is_(None))
        )
        or 0
    )
    missing_og = (
        db.scalar(
            select(func.count(Novel.id)).where(Novel.published.is_(True), Novel.og_image_path.is_(None))
        )
        or 0
    )
    return {
        "published": published,
        "missing_seo_title": missing_title,
        "missing_seo_description": missing_description,
        "missing_open_graph_image": missing_og,
    }


@router.post("/novels/{novel_id}/action")
def novel_action(novel_id: int, payload: AdminAction, db: Session = Depends(get_db)) -> dict:
    novel = db.get(Novel, novel_id)
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    result: dict = {"action": payload.action}
    queued_task: tuple[str, int] | None = None
    if payload.action in {"publish", "republish"}:
        decision = RightsEngine().enforce_publication(db, novel)
        if not decision.allowed:
            raise HTTPException(status_code=409, detail={"publication_blocked": list(decision.reasons)})
        result["published"] = True
    elif payload.action == "unpublish":
        novel.published = False
        novel.ads_eligible = False
    elif payload.action == "reject":
        novel.published = False
        novel.ads_eligible = False
        novel.content_type = "NON_TARGET"
        job = db.scalar(select(ImportJob).where(ImportJob.novel_id == novel.id).order_by(ImportJob.id.desc()))
        if job:
            job.status = ImportStatus.FAILED.value
            job.checkpoint = "CLASSIFY_FICTION"
            job.attempt_count = 10
            job.next_retry_at = None
            job.error = f"Candidate rejected by editorial classification: {payload.reason}"
        db.add(
            QualityIssue(
                novel_id=novel.id,
                import_job_id=job.id if job else None,
                code="NON_TARGET_CONTENT",
                severity="ERROR",
                message=payload.reason,
                blocking=True,
            )
        )
    elif payload.action == "disable_ads":
        novel.ads_eligible = False
        novel.monetization_status = MonetizationStatus.DISABLED.value
    elif payload.action == "enable_ads":
        eligible, status_value = MonetizationService().novel_eligibility(novel)
        novel.ads_eligible = eligible
        novel.monetization_status = status_value
        if not eligible:
            raise HTTPException(status_code=409, detail=f"Novel is not ad eligible: {status_value}")
    elif payload.action in {"reprocess", "reprocess_chapters"}:
        job = db.scalar(select(ImportJob).where(ImportJob.novel_id == novel.id).order_by(ImportJob.id.desc()))
        if not job:
            raise HTTPException(status_code=404, detail="Import job not found")
        novel.published = False
        novel.ads_eligible = False
        job.status = ImportStatus.PARSED.value
        job.next_retry_at = None
        queued_task = ("process_import", job.id)
    elif payload.action == "regenerate_cover":
        if get_settings().ai_image_provider != "http":
            raise HTTPException(
                status_code=409,
                detail="AI cover generation is disabled until the approved HTTP provider is configured.",
            )
        job = db.scalar(select(ImportJob).where(ImportJob.novel_id == novel.id).order_by(ImportJob.id.desc()))
        if not job:
            raise HTTPException(status_code=404, detail="Import job not found")
        job.status = ImportStatus.READY_FOR_COVER.value
        job.checkpoint = "GENERATE_COVER"
        job.next_retry_at = None
        queued_task = ("generate_cover", novel.id)
        result["approval_required"] = True
    elif payload.action == "ready_to_publish":
        job = db.scalar(select(ImportJob).where(ImportJob.novel_id == novel.id).order_by(ImportJob.id.desc()))
        if not job:
            raise HTTPException(status_code=404, detail="Import job not found")
        job.status = ImportStatus.READY_TO_PUBLISH.value
        queued_task = ("process_import", job.id)
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action=f"NOVEL_{payload.action.upper()}",
            entity_type="novel",
            entity_id=str(novel.id),
            details={"reason": payload.reason},
        )
    )
    db.commit()
    if queued_task:
        task_name, entity_id = queued_task
        task = generate_cover.delay(entity_id) if task_name == "generate_cover" else process_import.delay(entity_id)
        result["task_id"] = task.id
    return {**result, "novel_id": novel.id, "published": novel.published, "ads_eligible": novel.ads_eligible}


@router.post("/novels/{novel_id}/merge")
def merge_duplicate(
    novel_id: int,
    payload: MergeAction,
    db: Session = Depends(get_db),
) -> dict:
    source = db.get(Novel, novel_id)
    target = db.get(Novel, payload.target_novel_id)
    if not source or not target:
        raise HTTPException(status_code=404, detail="Source or target novel not found")
    if source.id == target.id:
        raise HTTPException(status_code=400, detail="A novel cannot be merged into itself")
    if target.merged_into_novel_id is not None:
        raise HTTPException(status_code=409, detail="Target novel is not a canonical record")
    source_work = db.get(Work, source.work_id)
    target_work = db.get(Work, target.work_id)
    if not source_work or not target_work:
        raise HTTPException(status_code=409, detail="Source or target work is missing")
    canonical = DeduplicationService.canonical_work(db, target_work)
    if canonical.id == source_work.id:
        raise HTTPException(status_code=409, detail="Merge would create a canonical-work cycle")

    source.published = False
    source.ads_eligible = False
    source.content_type = "NON_TARGET"
    source.merged_into_novel_id = target.id
    source_work.canonical_work_id = canonical.id
    for job in db.scalars(select(ImportJob).where(ImportJob.novel_id == source.id)).all():
        job.status = ImportStatus.FAILED.value
        job.attempt_count = 10
        job.next_retry_at = None
        job.error = f"Merged into canonical novel #{target.id}: {payload.reason}"
    db.add(
        QualityIssue(
            novel_id=source.id,
            code="DUPLICATE_MERGED",
            severity="INFO",
            message=f"Merged into canonical novel #{target.id}: {payload.reason}",
            blocking=True,
        )
    )
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="NOVEL_DUPLICATE_MERGED",
            entity_type="novel",
            entity_id=str(source.id),
            details={"target_novel_id": target.id, "reason": payload.reason},
        )
    )
    db.commit()
    return {
        "merged": True,
        "source_novel_id": source.id,
        "target_novel_id": target.id,
        "canonical_work_id": canonical.id,
    }


@router.get("/quality-issues")
def quality_issues(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": issue.id,
            "novel_id": issue.novel_id,
            "code": issue.code,
            "severity": issue.severity,
            "message": issue.message,
            "blocking": issue.blocking,
        }
        for issue in db.scalars(
            select(QualityIssue)
            .where(QualityIssue.resolved_at.is_(None))
            .order_by(QualityIssue.blocking.desc(), QualityIssue.created_at)
        ).all()
    ]


@router.get("/takedowns")
def takedowns(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "novel_id": item.novel_id,
            "requester_name": item.requester_name,
            "requester_email": item.requester_email,
            "claim": item.claim,
            "status": item.status,
            "created_at": item.created_at,
        }
        for item in db.scalars(select(TakedownRequest).order_by(TakedownRequest.created_at.desc())).all()
    ]


@router.post("/takedowns/{request_id}")
def update_takedown(request_id: int, payload: TakedownAction, db: Session = Depends(get_db)) -> dict:
    try:
        next_status = TakedownStatus(payload.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Unknown takedown status") from exc
    request = db.get(TakedownRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Takedown request not found")
    request.status = next_status.value
    request.resolution = payload.resolution
    if next_status in {TakedownStatus.TEMPORARILY_DISABLED, TakedownStatus.REMOVED} and request.novel_id:
        novel = db.get(Novel, request.novel_id)
        if novel:
            novel.published = False
            novel.ads_eligible = False
            if next_status == TakedownStatus.REMOVED:
                novel.rights_status = RightsStatus.REMOVED.value
    if next_status in {TakedownStatus.RESOLVED, TakedownStatus.RESTORED, TakedownStatus.REMOVED}:
        request.resolved_at = datetime.now(UTC)
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="TAKEDOWN_UPDATED",
            entity_type="takedown",
            entity_id=str(request.id),
            details=payload.model_dump(),
        )
    )
    db.commit()
    return {"id": request.id, "status": request.status}


@router.get("/contact-requests")
def contact_requests(db: Session = Depends(get_db)) -> list[dict]:
    return [
        {
            "id": item.id,
            "requester_name": item.requester_name,
            "requester_email": item.requester_email,
            "category": item.category,
            "message": item.message,
            "status": item.status,
            "resolution": item.resolution,
            "created_at": item.created_at,
        }
        for item in db.scalars(
            select(ContactRequest).order_by(ContactRequest.created_at.desc()).limit(500)
        ).all()
    ]


@router.post("/contact-requests/{request_id}")
def update_contact_request(
    request_id: int,
    payload: ContactAction,
    db: Session = Depends(get_db),
) -> dict:
    request = db.get(ContactRequest, request_id)
    if not request:
        raise HTTPException(status_code=404, detail="Contact request not found")
    request.status = payload.status
    request.resolution = payload.resolution
    request.resolved_at = datetime.now(UTC) if payload.status == "RESOLVED" else None
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="CONTACT_REQUEST_UPDATED",
            entity_type="contact_request",
            entity_id=str(request.id),
            details=payload.model_dump(),
        )
    )
    db.commit()
    return {"id": request.id, "status": request.status}
