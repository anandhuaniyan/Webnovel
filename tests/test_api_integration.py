from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.config import get_settings
from app.core.database import engine
from app.models import (
    Author,
    Chapter,
    Edition,
    ImportJob,
    Novel,
    NovelImage,
    RightsEvidence,
    RightsRecord,
    RightsReviewer,
    Source,
    SourceItem,
    Work,
)
from app.services.rights import RightsEngine
from app.services.search import SearchService
from app.services.storage import StorageService
from fastapi.testclient import TestClient
from sqlalchemy import inspect, update
from sqlalchemy.orm import Session

pytestmark = pytest.mark.integration


def test_migration_created_required_tables() -> None:
    tables = set(inspect(engine).get_table_names())
    required = {
        "users",
        "authors",
        "works",
        "editions",
        "novels",
        "chapters",
        "chapter_images",
        "novel_visual_profiles",
        "genres",
        "sources",
        "rights_records",
        "rights_reviewers",
        "rights_evidence",
        "import_jobs",
        "quality_issues",
        "reading_progress",
        "bookmarks",
        "ratings",
        "reviews",
        "contact_requests",
        "takedown_requests",
        "audit_logs",
    }
    assert required <= tables


def test_health_public_config_and_empty_fail_closed_catalogue(
    client: TestClient, db_session: Session
) -> None:
    db_session.execute(update(Novel).values(published=False))
    db_session.flush()
    assert client.get("/health").json()["status"] == "healthy"
    config = client.get("/api/config/public").json()
    assert config["adsense_enabled"] is False
    assert config["adsense_client_id"] == ""
    assert client.get("/api/novels").json()["total"] == 0
    assert client.get("/api/catalogue/stats").json() == {
        "novels": 0,
        "chapters": 0,
        "genres": 0,
    }


def test_policies_robots_sitemap_and_admin_boundary(client: TestClient) -> None:
    assert client.get("/privacy").status_code == 200
    assert client.get("/takedown").status_code == 200
    assert "Disallow: /api/" in client.get("/robots.txt").text
    sitemap = client.get("/sitemap.xml").text
    assert "/sitemaps/novels-1.xml" in sitemap
    assert "/sitemaps/chapters-1.xml" in sitemap
    assert "/admin" not in sitemap
    assert (
        client.get("/api/admin/dashboard", headers={"X-Admin-Key": "wrong"}).status_code
        == 403
    )


def test_private_reviewer_identity_is_admin_only(
    client: TestClient, db_session: Session
) -> None:
    novel = db_session.query(Novel).filter(Novel.published.is_(True)).first()
    if novel is None:
        pytest.skip("A published fixture is required for public privacy verification")
    rights = (
        db_session.query(RightsRecord)
        .filter(RightsRecord.edition_id == novel.edition_id)
        .order_by(RightsRecord.updated_at.desc())
        .first()
    )
    assert rights is not None
    marker = f"Private Reviewer {uuid4().hex}"
    reviewer = RightsReviewer(display_name=marker, reviewer_type="EXTERNAL", active=True)
    db_session.add(reviewer)
    db_session.flush()
    rights.reviewer_id = reviewer.id
    rights.verified_by = marker
    rights.human_review_status = "APPROVED"
    rights.reviewer_visibility = "PRIVATE"
    db_session.flush()

    public_api = client.get(f"/api/novels/{novel.slug}")
    public_page = client.get(f"/novels/{novel.slug}")
    novel_sitemap = client.get("/sitemaps/novels-1.xml")
    sitemap_index = client.get("/sitemap.xml")

    assert public_api.status_code == 200
    assert public_page.status_code == 200
    assert marker not in public_api.text
    assert marker not in public_page.text
    assert marker not in novel_sitemap.text
    assert marker not in sitemap_index.text
    assert "human_reviewer" not in public_api.json().get("rights_summary", {})

    assert client.get(f"/api/admin/rights/{rights.id}").status_code == 403
    admin = client.get(
        f"/api/admin/rights/{rights.id}",
        headers={"X-Admin-Key": get_settings().admin_api_key},
    )
    assert admin.status_code == 200
    assert admin.json()["human_reviewer"]["display_name"] == marker


def test_private_human_approval_advances_existing_pipeline_only_after_decision(
    client: TestClient, db_session: Session, monkeypatch, tmp_path
) -> None:
    suffix = uuid4().hex[:10]
    source = db_session.query(Source).first()
    assert source is not None
    author = Author(slug=f"approval-author-{suffix}", name=f"Approval Author {suffix}")
    db_session.add(author)
    db_session.flush()
    work = Work(title=f"Approval Story {suffix}", normalized_title=f"approval story {suffix}",
                primary_author_id=author.id, original_language="en", content_type="NOVEL")
    db_session.add(work)
    db_session.flush()
    edition = Edition(work_id=work.id, title=work.title, language="en",
                      completeness_status="UNKNOWN")
    db_session.add(edition)
    db_session.flush()
    novel = Novel(work_id=work.id, edition_id=edition.id, primary_author_id=author.id,
                  slug=f"approval-story-{suffix}", title=work.title, language="en",
                  content_type="NOVEL", rights_status="RESEARCHING", published=False)
    source_item = SourceItem(source_id=source.id, edition_id=edition.id,
                             external_id=f"approval-{suffix}", source_url="https://example.test/book",
                             raw_metadata={})
    db_session.add_all([novel, source_item])
    db_session.flush()
    job = ImportJob(source_item_id=source_item.id, novel_id=novel.id,
                    status="RIGHTS_CHECK", checkpoint="VERIFY_RIGHTS")
    reviewer = RightsReviewer(display_name=f"Private Approver {suffix}",
                              reviewer_type="EXTERNAL", active=True)
    rights = RightsRecord(work_id=work.id, edition_id=edition.id, status="RESEARCHING",
                          jurisdiction="SG", research_method="AI_ASSISTED_COPYRIGHT_RESEARCH",
                          research_provider="OpenAI", research_summary="Supporting research only.",
                          research_completed_at=datetime.now(UTC), human_review_status="PENDING",
                          manual_approval=False, review_reference=f"RIGHTS-TEST-{suffix}")
    db_session.add_all([job, reviewer, rights])
    db_session.flush()

    queued = []
    monkeypatch.setattr("app.api.admin.process_import.delay",
                        lambda job_id: queued.append(job_id) or SimpleNamespace(id="pipeline-test"))
    monkeypatch.setattr(StorageService, "__init__", lambda self: setattr(self, "root", tmp_path))
    monkeypatch.setattr(StorageService, "safe_path",
                        lambda self, category, relative: self.root / category / relative)

    response = client.post(
        f"/api/admin/rights/{rights.id}/approve",
        headers={"X-Admin-Key": get_settings().admin_api_key},
        json={"status": "PUBLIC_DOMAIN_VERIFIED", "reviewer_id": reviewer.id,
              "verification_method": "Independent human copyright and edition review",
              "evidence_description": "A legitimate human reviewer documented the publication decision.",
              "review_interval_days": 365},
    )

    assert response.status_code == 200
    assert response.json()["pipeline_task_id"] == "pipeline-test"
    db_session.refresh(job)
    db_session.refresh(rights)
    assert job.status == "RIGHTS_APPROVED"
    assert rights.human_review_status == "APPROVED"
    assert rights.reviewer_id == reviewer.id
    assert rights.verified_by is None
    assert queued == [job.id]


def test_authentication_and_account_boundary(client: TestClient) -> None:
    email = f"integration-{uuid4()}@example.com"
    response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "a-secure-test-password",
            "display_name": "Integration Reader",
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]
    me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == email
    assert client.get("/api/me").status_code == 401


def test_takedown_submission_is_functional(client: TestClient) -> None:
    response = client.post(
        "/api/takedown",
        json={
            "requester_name": "Rights Holder",
            "requester_email": "rights@example.com",
            "claim": "This is a detailed rights concern long enough to enter the tracked review workflow.",
            "evidence": "Supporting reference retained for investigation.",
        },
    )
    assert response.status_code == 201
    assert response.json()["status"] == "RECEIVED"


def test_contact_submission_and_admin_workflow(client: TestClient) -> None:
    response = client.post(
        "/api/contact-form",
        data={
            "requester_name": "Helpful Reader",
            "requester_email": "reader@example.com",
            "category": "ACCESSIBILITY",
            "message": "Please add a more visible focus indicator to reader controls.",
        },
    )
    assert response.status_code == 201
    assert "Message received" in response.text

    headers = {"X-Admin-Key": get_settings().admin_api_key}
    dashboard = client.get("/api/admin/dashboard", headers=headers)
    assert dashboard.status_code == 200
    assert dashboard.json()["contacts"]["open"] >= 1
    queue = client.get("/api/admin/contact-requests", headers=headers)
    assert queue.status_code == 200
    request_id = next(
        item["id"]
        for item in queue.json()
        if item["requester_email"] == "reader@example.com"
    )
    resolved = client.post(
        f"/api/admin/contact-requests/{request_id}",
        headers=headers,
        json={"status": "RESOLVED", "resolution": "Accessibility feedback recorded."},
    )
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "RESOLVED"


def test_admin_duplicate_merge_preserves_provenance_and_sets_canonical_work(
    client: TestClient,
    db_session: Session,
) -> None:
    suffix = uuid4().hex[:10]
    author = Author(
        slug=f"duplicate-author-{suffix}", name=f"Duplicate Author {suffix}"
    )
    db_session.add(author)
    db_session.flush()
    target_work = Work(
        title="Canonical Duplicate Story",
        normalized_title="canonical duplicate story",
        primary_author_id=author.id,
        content_type="NOVEL",
    )
    source_work = Work(
        title="Canonical Duplicate Story",
        normalized_title="canonical duplicate story",
        primary_author_id=author.id,
        content_type="NOVEL",
    )
    db_session.add_all([target_work, source_work])
    db_session.flush()
    target_edition = Edition(
        work_id=target_work.id,
        title=target_work.title,
        language="en",
        completeness_status="UNKNOWN",
    )
    source_edition = Edition(
        work_id=source_work.id,
        title=source_work.title,
        language="en",
        completeness_status="UNKNOWN",
    )
    db_session.add_all([target_edition, source_edition])
    db_session.flush()
    target = Novel(
        work_id=target_work.id,
        edition_id=target_edition.id,
        primary_author_id=author.id,
        slug=f"canonical-story-{suffix}",
        title=target_work.title,
        language="en",
    )
    source = Novel(
        work_id=source_work.id,
        edition_id=source_edition.id,
        primary_author_id=author.id,
        slug=f"duplicate-story-{suffix}",
        title=source_work.title,
        language="en",
    )
    db_session.add_all([target, source])
    db_session.flush()

    response = client.post(
        f"/api/admin/novels/{source.id}/merge",
        headers={"X-Admin-Key": get_settings().admin_api_key},
        json={
            "target_novel_id": target.id,
            "reason": "Independent editorial review confirmed both records represent the same work.",
        },
    )
    assert response.status_code == 200
    assert response.json()["canonical_work_id"] == target_work.id
    db_session.refresh(source)
    db_session.refresh(source_work)
    assert source.merged_into_novel_id == target.id
    assert source.content_type == "NON_TARGET"
    assert not source.published
    assert source_work.canonical_work_id == target_work.id

    cover = client.post(
        f"/api/admin/novels/{target.id}/action",
        headers={"X-Admin-Key": get_settings().admin_api_key},
        json={
            "action": "regenerate_cover",
            "reason": "Exercise the disabled-provider publication safety boundary.",
        },
    )
    assert cover.status_code == 409
    assert "disabled" in cover.json()["detail"]


def test_synthetic_full_publication_search_and_rights_recheck(
    db_session: Session,
) -> None:
    suffix = uuid4().hex[:10]
    author = Author(slug=f"arthur-conan-doyle-{suffix}", name="Arthur Conan Doyle")
    db_session.add(author)
    db_session.flush()
    work = Work(
        title="The Adventures of Sherlock Holmes",
        normalized_title="the adventures of sherlock holmes",
        primary_author_id=author.id,
        original_language="en",
        content_type="SHORT_STORY_COLLECTION",
    )
    db_session.add(work)
    db_session.flush()
    edition = Edition(
        work_id=work.id,
        title=work.title,
        language="en",
        completeness_status="COMPLETE",
    )
    db_session.add(edition)
    db_session.flush()
    novel = Novel(
        work_id=work.id,
        edition_id=edition.id,
        primary_author_id=author.id,
        slug=f"sherlock-holmes-{suffix}",
        title=work.title,
        description="A complete reviewed synthetic test record for search and publication gating.",
        language="en",
        content_type=work.content_type,
        completeness_status="COMPLETE",
        rights_status="PUBLIC_DOMAIN_VERIFIED",
        chapter_count=1,
        total_words=5_500,
        estimated_reading_minutes=25,
        quality_score=95,
        cover_path=f"storage/covers/{suffix}/portrait.webp",
        thumbnail_path=f"storage/covers/{suffix}/thumbnail.webp",
        og_image_path=f"storage/covers/{suffix}/open_graph.webp",
    )
    db_session.add(novel)
    db_session.flush()
    db_session.add_all(
        [
            Chapter(
                novel_id=novel.id,
                chapter_number=1,
                chapter_order=1,
                chapter_title="A Scandal in Bohemia",
                chapter_slug="a-scandal-in-bohemia",
                content_html="<p>Canonical synthetic test text.</p>",
                content_text="Canonical synthetic test text.",
                word_count=5_500,
                estimated_reading_minutes=25,
                source_hash="a" * 64,
                content_hash="b" * 64,
            ),
            NovelImage(
                novel_id=novel.id,
                image_type="portrait",
                path=novel.cover_path,
                width=1200,
                height=1800,
                mime_type="image/webp",
                content_hash="c" * 64,
                prompt_metadata={"test": True},
                approved=True,
            ),
            NovelImage(
                novel_id=novel.id,
                image_type="thumbnail",
                path=novel.thumbnail_path,
                width=400,
                height=600,
                mime_type="image/webp",
                content_hash="e" * 64,
                prompt_metadata={"test": True},
                approved=True,
            ),
            NovelImage(
                novel_id=novel.id,
                image_type="open_graph",
                path=novel.og_image_path,
                width=1200,
                height=630,
                mime_type="image/webp",
                content_hash="f" * 64,
                prompt_metadata={"test": True},
                approved=True,
            ),
        ]
    )
    rights = RightsRecord(
        work_id=work.id,
        edition_id=edition.id,
        status="PUBLIC_DOMAIN_VERIFIED",
        jurisdiction="SG",
        verification_method="Independent synthetic integration verification",
        verified_by="test suite",
        verified_at=datetime.now(UTC),
        next_review_at=datetime.now(UTC) + timedelta(days=365),
        manual_approval=True,
        human_review_status="APPROVED",
        reviewer_visibility="PRIVATE",
    )
    db_session.add(rights)
    db_session.flush()
    db_session.add(
        RightsEvidence(
            rights_record_id=rights.id,
            evidence_type="INDEPENDENT_MANUAL_REVIEW",
            description="Synthetic evidence proving that the publication gate works in integration tests.",
            content_hash="d" * 64,
        )
    )
    db_session.flush()

    decision = RightsEngine().enforce_publication(db_session, novel)
    db_session.flush()
    assert decision.allowed
    assert novel.published
    assert any(
        item.slug == novel.slug
        for item in SearchService().search(db_session, "sherlok holmes")
    )

    rights.next_review_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.flush()
    assert RightsEngine().recheck_due_rights(db_session) == 1
    assert not novel.published
    assert not novel.ads_eligible
