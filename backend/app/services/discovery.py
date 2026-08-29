from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import ImportStatus
from app.models import ImportJob, Source, SourceItem
from app.services.deduplication import DeduplicationService
from app.services.sources import GutenbergAdapter, SourceAdapter, StandardEbooksAdapter, WikisourceAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    "gutenberg": GutenbergAdapter,
    "standard_ebooks": StandardEbooksAdapter,
    "wikisource": WikisourceAdapter,
}


class DiscoveryService:
    def __init__(self) -> None:
        self.deduplication = DeduplicationService()

    def discover(self, db: Session, source_code: str, *, page: int = 1, limit: int = 20) -> dict:
        if source_code not in ADAPTERS:
            raise ValueError(f"unsupported source adapter: {source_code}")
        source = db.scalar(select(Source).where(Source.code == source_code, Source.enabled.is_(True)))
        if not source:
            raise LookupError(f"enabled source not configured: {source_code}")
        adapter = ADAPTERS[source_code]()
        candidates = asyncio.run(adapter.discover(page=page))[: min(max(limit, 1), 100)]
        created = skipped_nonfiction = existing = 0
        job_ids: list[int] = []
        for candidate in candidates:
            if not adapter.is_fiction(candidate):
                skipped_nonfiction += 1
                continue
            prior = self.deduplication.find_source_item(db, source.id, candidate.external_id)
            if prior:
                existing += 1
                continue
            source_item = SourceItem(
                source_id=source.id,
                external_id=candidate.external_id,
                source_url=candidate.source_url,
                metadata_url=candidate.metadata_url,
                download_url=candidate.download_url,
                media_type=candidate.media_type,
                raw_metadata=candidate.raw_metadata,
            )
            db.add(source_item)
            db.flush()
            job = ImportJob(
                source_item_id=source_item.id,
                status=ImportStatus.DISCOVERED.value,
                checkpoint="DISCOVER",
                payload={
                    "title": candidate.title,
                    "authors": list(candidate.authors),
                    "languages": list(candidate.languages),
                    "subjects": list(candidate.subjects),
                    "bookshelves": list(candidate.bookshelves),
                    "content_type": adapter.classify_content_type(candidate),
                    "source_licence_claim": candidate.licence_name,
                    "source_licence_url": candidate.licence_url,
                    "rights_warning": "Source claims are not publication approval.",
                },
            )
            db.add(job)
            db.flush()
            job_ids.append(job.id)
            created += 1
        db.commit()
        return {
            "source": source_code,
            "page": page,
            "received": len(candidates),
            "created": created,
            "existing": existing,
            "skipped_nonfiction": skipped_nonfiction,
            "job_ids": job_ids,
            "publication_status": "No candidate is published before independent rights review.",
        }
