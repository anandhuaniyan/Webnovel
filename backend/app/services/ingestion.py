from __future__ import annotations

import errno
import hashlib
import json
import re
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from slugify import slugify
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import CompletenessStatus, ImportStatus, RightsStatus
from app.models import (
    Author,
    Chapter,
    Edition,
    ImportJob,
    Novel,
    QualityIssue,
    RightsEvidence,
    RightsRecord,
    Source,
    SourceItem,
    Work,
)
from app.services.chapter_extraction import ChapterExtractionService
from app.services.deduplication import DeduplicationService, content_fingerprint, normalize_text
from app.services.quality import CompletenessService
from app.services.rights import RightsEngine
from app.services.storage import StorageService


class IngestionService:
    """Resumable, idempotent import state machine.

    It intentionally stops at RIGHTS_CHECK until an administrator supplies
    independent evidence and manually approves a jurisdiction-specific record.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.storage = StorageService()
        self.extractor = ChapterExtractionService()
        self.quality = CompletenessService()
        self.deduplication = DeduplicationService()
        self.rights = RightsEngine()

    def process(self, db: Session, job_id: int) -> dict:
        job = db.scalar(select(ImportJob).where(ImportJob.id == job_id).with_for_update())
        if not job:
            raise LookupError(f"import job not found: {job_id}")
        if job.status == ImportStatus.PUBLISHED.value:
            return self._summary(job, "already complete")
        if job.next_retry_at and job.next_retry_at > datetime.now(UTC):
            return self._summary(job, "retry not due")
        if job.status == ImportStatus.FAILED.value:
            resume_status = (job.payload or {}).get("resume_status")
            if resume_status not in {status.value for status in ImportStatus} - {
                ImportStatus.FAILED.value,
                ImportStatus.PUBLISHED.value,
            }:
                raise RuntimeError("failed import has no valid resume status")
            job.status = resume_status
            job.next_retry_at = None

        job.attempt_count += 1
        job.started_at = datetime.now(UTC)
        job.error = None
        db.commit()
        try:
            self._run(db, job)
            job.completed_at = datetime.now(UTC)
            db.commit()
            return self._summary(job, "processed")
        except Exception as exc:
            db.rollback()
            job = db.get(ImportJob, job_id)
            if job:
                payload = dict(job.payload or {})
                payload["resume_status"] = job.status
                job.payload = payload
                job.status = ImportStatus.FAILED.value
                job.error = str(exc)[:10_000]
                job.next_retry_at = datetime.now(UTC) + timedelta(
                    minutes=min(24 * 60, 2 ** min(job.attempt_count, 10))
                )
                db.commit()
            raise

    def _run(self, db: Session, job: ImportJob) -> None:
        if job.status == ImportStatus.DISCOVERED.value:
            self._materialize_metadata(db, job)
        if job.status == ImportStatus.METADATA_FETCHED.value:
            job.status = ImportStatus.RIGHTS_CHECK.value
            job.checkpoint = "VERIFY_RIGHTS"
            db.commit()
        if job.status == ImportStatus.RIGHTS_CHECK.value:
            return
        if job.status == ImportStatus.RIGHTS_APPROVED.value:
            self._download(db, job)
        if job.status == ImportStatus.DOWNLOADED.value:
            job.status = ImportStatus.PARSED.value
            job.checkpoint = "PARSE"
            db.commit()
        if job.status == ImportStatus.PARSED.value:
            self._extract_chapters(db, job)
        if job.status == ImportStatus.CHAPTERS_EXTRACTED.value:
            self._quality_check(db, job)
        if job.status == ImportStatus.QUALITY_CHECK.value:
            novel = db.get(Novel, job.novel_id)
            if novel and novel.completeness_status == CompletenessStatus.COMPLETE.value:
                job.status = ImportStatus.READY_FOR_COVER.value
                job.checkpoint = "GENERATE_COVER"
                db.commit()
        if job.status == ImportStatus.READY_FOR_COVER.value:
            return
        if job.status == ImportStatus.READY_TO_PUBLISH.value:
            novel = db.get(Novel, job.novel_id)
            if not novel:
                raise RuntimeError("job has no novel")
            decision = self.rights.enforce_publication(db, novel)
            if not decision.allowed:
                raise RuntimeError("publication blocked: " + "; ".join(decision.reasons))
            job.status = ImportStatus.PUBLISHED.value
            job.checkpoint = "PUBLISH"
            db.commit()

    def _materialize_metadata(self, db: Session, job: ImportJob) -> None:
        source_item = db.get(SourceItem, job.source_item_id)
        if not source_item:
            raise RuntimeError("source item missing")
        source = db.get(Source, source_item.source_id)
        payload = job.payload or {}
        title = payload.get("title") or source_item.raw_metadata.get("title") or "Untitled"
        author_name = (payload.get("authors") or ["Unknown"])[0]
        language = (payload.get("languages") or ["en"])[0]
        content_type = payload.get("content_type") or "FICTION"
        year = self._extract_year(source_item.raw_metadata)

        author = db.scalar(select(Author).where(Author.name == author_name))
        if not author:
            author = Author(slug=self._unique_slug(db, Author, author_name), name=author_name)
            db.add(author)
            db.flush()

        duplicate = self.deduplication.find_work(db, title=title, author_name=author_name, year=year)
        if duplicate:
            work = db.get(Work, duplicate.entity_id)
        else:
            work = Work(
                title=title,
                normalized_title=normalize_text(title),
                primary_author_id=author.id,
                original_language=language,
                first_publication_year=year,
                content_type=content_type,
            )
            db.add(work)
            db.flush()

        edition = Edition(
            work_id=work.id,
            title=title,
            language=language,
            completeness_status=CompletenessStatus.UNKNOWN.value,
        )
        db.add(edition)
        db.flush()
        source_item.edition_id = edition.id

        novel = db.scalar(select(Novel).where(Novel.work_id == work.id))
        if not novel:
            novel = Novel(
                work_id=work.id,
                edition_id=edition.id,
                primary_author_id=author.id,
                slug=self._unique_slug(db, Novel, f"{title}-{source.code}-{source_item.external_id}"),
                title=title,
                language=language,
                content_type=content_type,
                rights_status=RightsStatus.RESEARCHING.value,
                completeness_status=CompletenessStatus.UNKNOWN.value,
                published=False,
                ads_eligible=False,
                description=None,
            )
            db.add(novel)
            db.flush()
        rights = RightsRecord(
            work_id=work.id,
            edition_id=edition.id,
            status=RightsStatus.RESEARCHING.value,
            jurisdiction=self.settings.rights_jurisdiction,
            licence_name=payload.get("source_licence_claim"),
            licence_url=payload.get("source_licence_url"),
            verification_method="Pending independent legal/rights review",
            manual_approval=False,
            notes="Source availability is not publication permission.",
        )
        db.add(rights)
        db.flush()
        evidence_path = self._archive_rights_claim(source, source_item, payload)
        db.add(
            RightsEvidence(
                rights_record_id=rights.id,
                evidence_type="SOURCE_CLAIM_UNVERIFIED",
                source_url=payload.get("source_licence_url"),
                local_path=str(evidence_path.relative_to(self.settings.project_root)),
                description="Unverified source-provided licence claim; independent evidence is still required.",
                content_hash=hashlib.sha256(evidence_path.read_bytes()).hexdigest(),
            )
        )
        job.novel_id = novel.id
        job.status = ImportStatus.METADATA_FETCHED.value
        job.checkpoint = "FETCH_METADATA"
        db.commit()

    def _download(self, db: Session, job: ImportJob) -> None:
        source_item = db.get(SourceItem, job.source_item_id)
        source = db.get(Source, source_item.source_id) if source_item else None
        if not source_item or not source or not source_item.download_url:
            raise RuntimeError("downloadable source is missing")
        extension = self._extension(source_item)
        target = self.storage.safe_path(
            "raw_books", f"{source.code}/{source_item.external_id}/original{extension}"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            temporary = self.storage.safe_path("temporary", f"download-{job.id}{extension}.part")
            with httpx.stream(
                "GET", source_item.download_url, timeout=120, follow_redirects=True
            ) as response:
                response.raise_for_status()
                with temporary.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 1024):
                        handle.write(chunk)
            self._promote_download(temporary, target)
        source_item.archived_path = str(target.relative_to(self.settings.project_root))
        source_item.source_hash = self.storage.sha256(target)
        job.status = ImportStatus.DOWNLOADED.value
        job.checkpoint = "ARCHIVE_RAW_SOURCE"
        db.commit()

    def _extract_chapters(self, db: Session, job: ImportJob) -> None:
        source_item = db.get(SourceItem, job.source_item_id)
        novel = db.get(Novel, job.novel_id)
        if not source_item or not source_item.archived_path or not novel:
            raise RuntimeError("source archive or novel is missing")
        source_path = (self.settings.project_root / source_item.archived_path).resolve()
        chapters = self.extractor.extract(source_path)
        db.execute(delete(Chapter).where(Chapter.novel_id == novel.id))
        for chapter in chapters:
            db.add(
                Chapter(
                    novel_id=novel.id,
                    chapter_number=chapter.number,
                    chapter_order=chapter.order,
                    chapter_title=chapter.title,
                    chapter_slug=chapter.slug,
                    content_html=chapter.content_html,
                    content_text=chapter.content_text,
                    word_count=chapter.word_count,
                    estimated_reading_minutes=chapter.estimated_reading_minutes,
                    source_hash=chapter.source_hash,
                    content_hash=chapter.content_hash,
                )
            )
        novel.chapter_count = len(chapters)
        novel.total_words = sum(chapter.word_count for chapter in chapters)
        novel.estimated_reading_minutes = sum(chapter.estimated_reading_minutes for chapter in chapters)
        edition = db.get(Edition, novel.edition_id)
        edition.content_hash = content_fingerprint("\n".join(chapter.content_text for chapter in chapters))
        job.status = ImportStatus.CHAPTERS_EXTRACTED.value
        job.checkpoint = "DETECT_CHAPTERS"
        db.commit()

    def _quality_check(self, db: Session, job: ImportJob) -> None:
        novel = db.get(Novel, job.novel_id)
        if not novel:
            raise RuntimeError("novel is missing")
        rows = db.scalars(
            select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.chapter_order)
        ).all()
        extracted = [
            self.extractor._build(
                chapter.chapter_order,
                chapter.chapter_title,
                chapter.content_html,
                chapter.content_text.encode(),
            )
            for chapter in rows
        ]
        status, findings = self.quality.inspect(extracted)
        novel.completeness_status = status
        edition = db.get(Edition, novel.edition_id)
        edition.completeness_status = status
        db.execute(delete(QualityIssue).where(QualityIssue.import_job_id == job.id))
        for finding in findings:
            db.add(
                QualityIssue(
                    novel_id=novel.id,
                    import_job_id=job.id,
                    code=finding.code,
                    severity=finding.severity,
                    message=finding.message,
                    blocking=finding.blocking,
                )
            )
        novel.quality_score = max(0, 100 - sum(20 if item.severity == "ERROR" else 7 for item in findings))
        job.status = ImportStatus.QUALITY_CHECK.value
        job.checkpoint = "QUALITY_CHECK"
        db.commit()

    def _archive_rights_claim(self, source: Source, source_item: SourceItem, payload: dict) -> Path:
        target = self.storage.safe_path(
            "rights_evidence", f"{source.code}/{source_item.external_id}/source-claim.json"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {
                    "captured_at": datetime.now(UTC).isoformat(),
                    "source": source.code,
                    "source_url": source_item.source_url,
                    "licence_claim": payload.get("source_licence_claim"),
                    "licence_url": payload.get("source_licence_url"),
                    "warning": "This source claim is not independent rights verification.",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return target

    @staticmethod
    def _promote_download(temporary: Path, target: Path) -> None:
        try:
            temporary.replace(target)
        except OSError as exc:
            if exc.errno != errno.EXDEV:
                raise
            staged = target.with_suffix(f"{target.suffix}.part")
            shutil.copyfile(temporary, staged)
            staged.replace(target)
            temporary.unlink()

    @staticmethod
    def _extract_year(metadata: dict) -> int | None:
        for field in ("copyright_year", "publication_year", "release_date"):
            value = metadata.get(field)
            match = re.search(r"\b(1[0-9]{3}|20[0-9]{2})\b", str(value or ""))
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _extension(source_item: SourceItem) -> str:
        media = source_item.media_type or ""
        if "epub" in media:
            return ".epub"
        if "html" in media:
            return ".html"
        return ".txt"

    @staticmethod
    def _unique_slug(db: Session, model: type, value: str) -> str:
        base = slugify(value)[:200] or "untitled"
        candidate = base
        suffix = 2
        while db.scalar(select(model.id).where(model.slug == candidate)):
            candidate = f"{base[:190]}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _summary(job: ImportJob, message: str) -> dict:
        return {
            "job_id": job.id,
            "novel_id": job.novel_id,
            "status": job.status,
            "checkpoint": job.checkpoint,
            "attempt_count": job.attempt_count,
            "message": message,
        }
