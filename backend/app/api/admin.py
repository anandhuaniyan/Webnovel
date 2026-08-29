from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
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
    ContactRequest,
    ImportJob,
    Novel,
    NovelImage,
    QualityIssue,
    Review,
    RightsEvidence,
    RightsRecord,
    SourceItem,
    TakedownRequest,
    Work,
)
from app.services.deduplication import DeduplicationService
from app.services.monetization import MonetizationService
from app.services.rights import RightsEngine
from app.services.storage import StorageService
from app.workers.tasks import discover, generate_cover, process_import

router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


class RightsApproval(BaseModel):
    status: str
    licence_name: str | None = None
    licence_version: str | None = None
    licence_url: str | None = None
    attribution_text: str | None = None
    verification_method: str = Field(min_length=10, max_length=255)
    verified_by: str = Field(min_length=2, max_length=255)
    evidence_url: str | None = None
    evidence_description: str = Field(min_length=20, max_length=5000)
    review_interval_days: int = Field(default=365, ge=30, le=3650)


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


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)) -> dict:
    def count(model, *filters) -> int:
        return db.scalar(select(func.count(model.id)).where(*filters)) or 0

    return {
        "catalogue": {
            "works": count(Novel),
            "published": count(Novel, Novel.published.is_(True)),
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
        },
        "media": {
            "covers_awaiting_approval": count(NovelImage, NovelImage.approved.is_(False)),
            "published_without_cover": count(Novel, Novel.published.is_(True), Novel.cover_path.is_(None)),
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
    return [
        {
            "rights_record_id": record.id,
            "novel_id": novel.id,
            "edition_id": record.edition_id,
            "title": novel.title,
            "status": record.status,
            "jurisdiction": record.jurisdiction,
            "licence_claim": record.licence_name,
            "licence_url": record.licence_url,
            "notes": record.notes,
        }
        for record, novel in rows
    ]


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
    record.verified_by = payload.verified_by
    record.verified_at = datetime.now(UTC)
    record.next_review_at = record.verified_at + timedelta(days=payload.review_interval_days)
    record.manual_approval = True

    evidence_root = StorageService().safe_path("rights_evidence", f"manual/{record.id}")
    evidence_root.mkdir(parents=True, exist_ok=True)
    evidence_path = evidence_root / f"approval-{int(record.verified_at.timestamp())}.json"
    evidence_path.write_text(
        json.dumps(
            {
                "source_url": payload.evidence_url,
                "description": payload.evidence_description,
                "verified_by": payload.verified_by,
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
    db.add(
        AuditLog(
            actor_type="ADMIN_KEY",
            action="RIGHTS_APPROVED",
            entity_type="rights_record",
            entity_id=str(record.id),
            details=payload.model_dump(mode="json"),
        )
    )
    db.commit()
    return {"approved": True, "status": record.status, "next_review_at": record.next_review_at}


@router.post("/rights/{record_id}/reject")
def reject_rights(record_id: int, payload: ModerationAction, db: Session = Depends(get_db)) -> dict:
    record = db.get(RightsRecord, record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Rights record not found")
    record.status = RightsStatus.RESTRICTED.value
    record.manual_approval = False
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
            details={"reason": payload.reason},
        )
    )
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
        process_import.delay(job.id)
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
        task = generate_cover.delay(novel.id)
        result["task_id"] = task.id
        result["approval_required"] = True
    elif payload.action == "ready_to_publish":
        job = db.scalar(select(ImportJob).where(ImportJob.novel_id == novel.id).order_by(ImportJob.id.desc()))
        if not job:
            raise HTTPException(status_code=404, detail="Import job not found")
        job.status = ImportStatus.READY_TO_PUBLISH.value
        process_import.delay(job.id)
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
