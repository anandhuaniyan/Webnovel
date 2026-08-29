from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Author, Edition, SourceItem, Work


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        " " if unicodedata.category(character)[0] in {"P", "S"} else character for character in value
    )
    value = value.encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def content_fingerprint(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class DuplicateMatch:
    entity_type: str
    entity_id: int
    reason: str


class DeduplicationService:
    @staticmethod
    def canonical_work(db: Session, work: Work) -> Work:
        seen = {work.id}
        while work.canonical_work_id:
            if work.canonical_work_id in seen:
                raise RuntimeError("canonical work chain contains a cycle")
            seen.add(work.canonical_work_id)
            canonical = db.get(Work, work.canonical_work_id)
            if canonical is None:
                break
            work = canonical
        return work

    def find_work(
        self,
        db: Session,
        *,
        title: str,
        author_name: str | None,
        year: int | None,
        wikidata_id: str | None = None,
    ) -> DuplicateMatch | None:
        if wikidata_id:
            work = db.scalar(select(Work).where(Work.wikidata_id == wikidata_id))
            if work:
                canonical = self.canonical_work(db, work)
                return DuplicateMatch("work", canonical.id, "matching Wikidata identifier")
        normalized_title = normalize_text(title)
        statement = select(Work).where(Work.normalized_title == normalized_title)
        if year:
            statement = statement.where(
                or_(Work.first_publication_year == year, Work.first_publication_year.is_(None))
            )
        candidates = db.scalars(statement).all()
        normalized_author = normalize_text(author_name or "")
        for work in candidates:
            if not normalized_author:
                canonical = self.canonical_work(db, work)
                return DuplicateMatch("work", canonical.id, "matching normalized title and year")
            author = db.get(Author, work.primary_author_id) if work.primary_author_id else None
            if author and normalize_text(author.name) == normalized_author:
                canonical = self.canonical_work(db, work)
                return DuplicateMatch("work", canonical.id, "matching normalized title, author, and year")
        return None

    def find_source_item(self, db: Session, source_id: int, external_id: str) -> SourceItem | None:
        return db.scalar(
            select(SourceItem).where(SourceItem.source_id == source_id, SourceItem.external_id == external_id)
        )

    def find_edition_by_hash(self, db: Session, fingerprint: str) -> Edition | None:
        return db.scalar(select(Edition).where(Edition.content_hash == fingerprint))
