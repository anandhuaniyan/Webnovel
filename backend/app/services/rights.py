from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.enums import APPROVED_RIGHTS_STATUSES, CompletenessStatus, MonetizationStatus, RightsStatus
from app.models import Novel, NovelImage, QualityIssue, RightsEvidence, RightsRecord


@dataclass(frozen=True)
class PublicationDecision:
    allowed: bool
    reasons: tuple[str, ...]


class RightsEngine:
    """Fail-closed publication policy.

    Automated source metadata can create and enrich a rights record, but it can
    never mark a work verified. An approved status requires a manual approval,
    jurisdiction, evidence, a verification method, and a future review date.
    """

    def __init__(self, rules_path: Path | None = None):
        settings = get_settings()
        self.rules_path = rules_path or settings.rights_rules_path
        self.rules = self._load_rules(self.rules_path)

    @staticmethod
    def _load_rules(path: Path) -> dict:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {
                "default_jurisdiction": "SG",
                "automatic_public_domain_approval": False,
                "manual_legal_review_required": True,
            }

    def assess_record(self, db: Session, record: RightsRecord) -> PublicationDecision:
        reasons: list[str] = []
        try:
            status = RightsStatus(record.status)
        except ValueError:
            return PublicationDecision(False, ("unknown rights status",))

        if status not in APPROVED_RIGHTS_STATUSES:
            reasons.append(f"rights status {status.value} is not approved")
        if not record.manual_approval:
            reasons.append("manual rights approval is missing")
        if getattr(record, "human_review_required", True) and getattr(
            record, "human_review_status", "PENDING"
        ) != "APPROVED":
            reasons.append("human rights review is not approved")
        if not (getattr(record, "reviewer_id", None) or getattr(record, "verified_by", None)):
            reasons.append("private human reviewer identity is missing")
        if not record.jurisdiction:
            reasons.append("jurisdiction is missing")
        if not record.verification_method:
            reasons.append("verification method is missing")
        if not record.verified_at:
            reasons.append("verification date is missing")
        now = datetime.now(UTC)
        if not record.next_review_at or record.next_review_at <= now:
            reasons.append("rights review is due or missing")
        evidence_count = db.scalar(
            select(func.count(RightsEvidence.id)).where(
                RightsEvidence.rights_record_id == record.id,
                RightsEvidence.evidence_type == "INDEPENDENT_MANUAL_REVIEW",
            )
        )
        if not evidence_count:
            reasons.append("independent rights evidence is missing")
        if status in {
            RightsStatus.LICENSE_VERIFIED,
            RightsStatus.CC0_VERIFIED,
            RightsStatus.CC_BY_VERIFIED,
            RightsStatus.CC_BY_SA_VERIFIED,
        } and (not record.licence_name or not record.licence_url):
            reasons.append("verified licence name and URL are required")
        if (
            status in {RightsStatus.CC_BY_VERIFIED, RightsStatus.CC_BY_SA_VERIFIED}
            and not record.attribution_text
        ):
            reasons.append("required licence attribution is missing")
        return PublicationDecision(not reasons, tuple(reasons))

    def assess_novel(self, db: Session, novel: Novel) -> PublicationDecision:
        reasons: list[str] = []
        if novel.merged_into_novel_id is not None:
            reasons.append("novel was merged into a canonical record")
        if novel.completeness_status != CompletenessStatus.COMPLETE.value:
            reasons.append("edition is not verified complete")
        record = db.scalar(
            select(RightsRecord)
            .where(RightsRecord.edition_id == novel.edition_id)
            .order_by(RightsRecord.updated_at.desc())
            .limit(1)
        )
        if record is None:
            reasons.append("rights record is missing")
        else:
            reasons.extend(self.assess_record(db, record).reasons)
        blocking_issues = db.scalar(
            select(func.count(QualityIssue.id)).where(
                QualityIssue.novel_id == novel.id,
                QualityIssue.blocking.is_(True),
                QualityIssue.resolved_at.is_(None),
            )
        )
        if blocking_issues:
            reasons.append(f"{blocking_issues} blocking quality issue(s) remain")
        if novel.chapter_count <= 0 or novel.total_words <= 0:
            reasons.append("readable chapter content is missing")
        approved_cover_types = set(
            db.scalars(
                select(NovelImage.image_type).where(
                    NovelImage.novel_id == novel.id,
                    NovelImage.approved.is_(True),
                )
            ).all()
        )
        if not {"portrait", "thumbnail", "open_graph"} <= approved_cover_types or not all(
            (novel.cover_path, novel.thumbnail_path, novel.og_image_path)
        ):
            reasons.append("approved portrait, thumbnail, and OpenGraph covers are required")
        return PublicationDecision(not reasons, tuple(reasons))

    def enforce_publication(self, db: Session, novel: Novel) -> PublicationDecision:
        decision = self.assess_novel(db, novel)
        if decision.allowed:
            novel.published = True
            novel.rights_status = db.scalar(
                select(RightsRecord.status)
                .where(RightsRecord.edition_id == novel.edition_id)
                .order_by(RightsRecord.updated_at.desc())
                .limit(1)
            )
            novel.published_at = novel.published_at or datetime.now(UTC)
        else:
            novel.published = False
            novel.ads_eligible = False
            novel.monetization_status = MonetizationStatus.RIGHTS_UNCERTAIN.value
        return decision

    def recheck_due_rights(self, db: Session) -> int:
        now = datetime.now(UTC)
        due_records = db.scalars(
            select(RightsRecord).where(
                RightsRecord.next_review_at.is_not(None), RightsRecord.next_review_at <= now
            )
        ).all()
        affected_ids: set[int] = set()
        for record in due_records:
            record.status = RightsStatus.RESEARCHING.value
            record.manual_approval = False
            record.human_review_status = "PENDING"
            novels = db.scalars(select(Novel).where(Novel.edition_id == record.edition_id)).all()
            for novel in novels:
                novel.published = False
                novel.ads_eligible = False
                novel.rights_status = RightsStatus.RESEARCHING.value
                novel.monetization_status = MonetizationStatus.RIGHTS_UNCERTAIN.value
                affected_ids.add(novel.id)
        published = db.scalars(select(Novel).where(Novel.published.is_(True))).all()
        for novel in published:
            decision = self.assess_novel(db, novel)
            if not decision.allowed:
                novel.published = False
                novel.ads_eligible = False
                novel.monetization_status = MonetizationStatus.RIGHTS_UNCERTAIN.value
                affected_ids.add(novel.id)
        db.commit()
        return len(affected_ids)
