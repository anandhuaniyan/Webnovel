from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core.enums import CompletenessStatus, MonetizationStatus, RightsStatus
from app.services.monetization import MonetizationService
from app.services.rights import RightsEngine


class ScalarDatabase:
    def __init__(self, *values):
        self.values = iter(values)

    def scalar(self, statement):
        return next(self.values)


def approved_record(**overrides):
    values = {
        "id": 1,
        "status": RightsStatus.PUBLIC_DOMAIN_VERIFIED.value,
        "manual_approval": True,
        "human_review_required": True,
        "human_review_status": "APPROVED",
        "reviewer_id": 7,
        "verified_by": None,
        "jurisdiction": "SG",
        "verification_method": "Independent manual legal and provenance review",
        "verified_at": datetime.now(timezone.utc),
        "next_review_at": datetime.now(timezone.utc) + timedelta(days=365),
        "licence_name": None,
        "licence_url": None,
        "attribution_text": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_rights_requires_independent_evidence() -> None:
    decision = RightsEngine().assess_record(ScalarDatabase(0), approved_record())

    assert not decision.allowed
    assert "independent rights evidence is missing" in decision.reasons


def test_ai_research_never_substitutes_for_human_approval() -> None:
    record = approved_record(
        manual_approval=False,
        human_review_status="PENDING",
        reviewer_id=None,
        research_method="AI_ASSISTED_COPYRIGHT_RESEARCH",
        research_provider="OpenAI",
        research_completed_at=datetime.now(timezone.utc),
    )

    decision = RightsEngine().assess_record(ScalarDatabase(1), record)

    assert not decision.allowed
    assert "manual rights approval is missing" in decision.reasons
    assert "human rights review is not approved" in decision.reasons
    assert "private human reviewer identity is missing" in decision.reasons


def test_attribution_licence_and_review_date_are_enforced() -> None:
    record = approved_record(
        status=RightsStatus.CC_BY_VERIFIED.value,
        licence_name="CC BY",
        licence_url=None,
        attribution_text=None,
        next_review_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    decision = RightsEngine().assess_record(ScalarDatabase(1), record)

    assert not decision.allowed
    assert "verified licence name and URL are required" in decision.reasons
    assert "required licence attribution is missing" in decision.reasons
    assert "rights review is due or missing" in decision.reasons


def test_monetization_rejects_thin_or_incomplete_pages() -> None:
    service = MonetizationService()
    novel = SimpleNamespace(
        published=True,
        completeness_status=CompletenessStatus.COMPLETE.value,
        ads_eligible=True,
        monetization_status=MonetizationStatus.NOT_REVIEWED.value,
        total_words=1_000,
        description=None,
        quality_score=95,
    )

    assert service.novel_eligibility(novel) == (
        False,
        MonetizationStatus.LOW_VALUE.value,
    )
    novel.completeness_status = CompletenessStatus.INCOMPLETE.value
    assert service.novel_eligibility(novel) == (
        False,
        MonetizationStatus.DISABLED.value,
    )
