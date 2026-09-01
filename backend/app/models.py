from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import (
    CompletenessStatus,
    IllustrationMode,
    ImportStatus,
    MonetizationStatus,
    RightsStatus,
    TakedownStatus,
)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    consent_preferences: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    reader_settings: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)


class Author(TimestampMixin, Base):
    __tablename__ = "authors"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    sort_name: Mapped[str | None] = mapped_column(String(255))
    biography: Mapped[str | None] = mapped_column(Text)
    birth_date: Mapped[date | None] = mapped_column(Date)
    death_date: Mapped[date | None] = mapped_column(Date)
    death_year: Mapped[int | None] = mapped_column(Integer)
    country: Mapped[str | None] = mapped_column(String(2))
    verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wikidata_id: Mapped[str | None] = mapped_column(String(30), unique=True)


class Work(TimestampMixin, Base):
    __tablename__ = "works"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    canonical_work_id: Mapped[int | None] = mapped_column(
        ForeignKey("works.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), index=True)
    normalized_title: Mapped[str] = mapped_column(String(500), index=True)
    primary_author_id: Mapped[int | None] = mapped_column(
        ForeignKey("authors.id", ondelete="SET NULL"), index=True
    )
    original_language: Mapped[str | None] = mapped_column(String(20))
    country_of_origin: Mapped[str | None] = mapped_column(String(2))
    first_publication_year: Mapped[int | None] = mapped_column(Integer)
    wikidata_id: Mapped[str | None] = mapped_column(String(30), unique=True)
    content_type: Mapped[str] = mapped_column(String(30), default="NOVEL", nullable=False)


class Edition(TimestampMixin, Base):
    __tablename__ = "editions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(500))
    language: Mapped[str] = mapped_column(String(20), index=True)
    publication_country: Mapped[str | None] = mapped_column(String(2))
    edition_year: Mapped[int | None] = mapped_column(Integer)
    publisher: Mapped[str | None] = mapped_column(String(255))
    translator_name: Mapped[str | None] = mapped_column(String(255))
    translator_death_year: Mapped[int | None] = mapped_column(Integer)
    isbn: Mapped[str | None] = mapped_column(String(32), unique=True)
    completeness_status: Mapped[str] = mapped_column(
        String(30), default=CompletenessStatus.UNKNOWN.value, nullable=False
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class Novel(TimestampMixin, Base):
    __tablename__ = "novels"
    __table_args__ = (
        CheckConstraint("quality_score >= 0 AND quality_score <= 100", name="ck_novels_quality_score"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    merged_into_novel_id: Mapped[int | None] = mapped_column(
        ForeignKey("novels.id", ondelete="SET NULL"), index=True
    )
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), unique=True)
    edition_id: Mapped[int] = mapped_column(ForeignKey("editions.id", ondelete="RESTRICT"), unique=True)
    primary_author_id: Mapped[int | None] = mapped_column(
        ForeignKey("authors.id", ondelete="SET NULL"), index=True
    )
    slug: Mapped[str] = mapped_column(String(240), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), index=True)
    alternative_title: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    ai_synopsis: Mapped[str | None] = mapped_column(Text)
    themes: Mapped[str | None] = mapped_column(Text)
    setting: Mapped[str | None] = mapped_column(Text)
    character_guide: Mapped[str | None] = mapped_column(Text)
    literary_context: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(20), index=True)
    content_type: Mapped[str] = mapped_column(String(30), default="NOVEL", nullable=False)
    completeness_status: Mapped[str] = mapped_column(
        String(30), default=CompletenessStatus.UNKNOWN.value, nullable=False, index=True
    )
    rights_status: Mapped[str] = mapped_column(
        String(40), default=RightsStatus.UNVERIFIED.value, nullable=False, index=True
    )
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    featured: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    ads_eligible: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    monetization_status: Mapped[str] = mapped_column(
        String(30), default=MonetizationStatus.NOT_REVIEWED.value, nullable=False
    )
    illustration_mode: Mapped[str] = mapped_column(
        String(30), default=IllustrationMode.NONE.value, nullable=False
    )
    quality_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reading_difficulty: Mapped[str | None] = mapped_column(String(40))
    total_words: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_reading_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cover_path: Mapped[str | None] = mapped_column(String(1000))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1000))
    og_image_path: Mapped[str | None] = mapped_column(String(1000))
    seo_title: Mapped[str | None] = mapped_column(String(255))
    seo_description: Mapped[str | None] = mapped_column(String(320))
    average_rating: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=0, nullable=False)
    rating_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    view_count: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(alternative_title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B') || "
            "setweight(to_tsvector('english', coalesce(themes, '')), 'C')",
            persisted=True,
        ),
    )


Index("ix_novels_search_vector", Novel.search_vector, postgresql_using="gin")
Index(
    "ix_novels_title_trgm",
    Novel.title,
    postgresql_using="gin",
    postgresql_ops={"title": "gin_trgm_ops"},
)


class NovelVisualProfile(TimestampMixin, Base):
    __tablename__ = "novel_visual_profiles"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    novel_id: Mapped[int] = mapped_column(
        ForeignKey("novels.id", ondelete="CASCADE"), unique=True, index=True
    )
    historical_period: Mapped[str | None] = mapped_column(String(255))
    environments: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    recurring_characters: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    atmosphere: Mapped[str | None] = mapped_column(String(500))
    illustration_style: Mapped[str] = mapped_column(
        String(255), default="cinematic editorial storybook illustration", nullable=False
    )
    lighting_style: Mapped[str] = mapped_column(
        String(255), default="naturalistic period-appropriate light", nullable=False
    )
    color_palette: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    visual_motifs: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    prompt_constraints: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)


class Chapter(TimestampMixin, Base):
    __tablename__ = "chapters"
    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_order", name="uq_chapters_novel_order"),
        UniqueConstraint("novel_id", "chapter_slug", name="uq_chapters_novel_slug"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    chapter_number: Mapped[int | None] = mapped_column(Integer)
    chapter_order: Mapped[int] = mapped_column(Integer)
    chapter_title: Mapped[str] = mapped_column(String(500))
    chapter_slug: Mapped[str] = mapped_column(String(240))
    content_html: Mapped[str] = mapped_column(Text)
    content_text: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    estimated_reading_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)


class Genre(TimestampMixin, Base):
    __tablename__ = "genres"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    introduction: Mapped[str | None] = mapped_column(Text)


class NovelGenre(Base):
    __tablename__ = "novel_genres"

    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(ForeignKey("genres.id", ondelete="CASCADE"), primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Tag(TimestampMixin, Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class NovelTag(Base):
    __tablename__ = "novel_tags"

    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class Series(TimestampMixin, Base):
    __tablename__ = "series"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)


class SeriesMember(Base):
    __tablename__ = "series_members"

    series_id: Mapped[int] = mapped_column(ForeignKey("series.id", ondelete="CASCADE"), primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)


class Source(TimestampMixin, Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    base_url: Mapped[str] = mapped_column(String(1000))
    adapter: Mapped[str] = mapped_column(String(120))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    trust_score: Mapped[int] = mapped_column(Integer, default=50, nullable=False)
    terms_url: Mapped[str | None] = mapped_column(String(1000))


class SourceItem(TimestampMixin, Base):
    __tablename__ = "source_items"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_source_items_external"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    edition_id: Mapped[int | None] = mapped_column(ForeignKey("editions.id", ondelete="SET NULL"), index=True)
    external_id: Mapped[str] = mapped_column(String(255))
    source_url: Mapped[str] = mapped_column(String(1500))
    metadata_url: Mapped[str | None] = mapped_column(String(1500))
    download_url: Mapped[str | None] = mapped_column(String(1500))
    media_type: Mapped[str | None] = mapped_column(String(120))
    raw_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(64))
    archived_path: Mapped[str | None] = mapped_column(String(1000))
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RightsRecord(TimestampMixin, Base):
    __tablename__ = "rights_records"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id", ondelete="CASCADE"), index=True)
    edition_id: Mapped[int | None] = mapped_column(ForeignKey("editions.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default=RightsStatus.UNVERIFIED.value, index=True)
    jurisdiction: Mapped[str] = mapped_column(String(10), index=True)
    licence_name: Mapped[str | None] = mapped_column(String(255))
    licence_version: Mapped[str | None] = mapped_column(String(80))
    licence_url: Mapped[str | None] = mapped_column(String(1500))
    attribution_text: Mapped[str | None] = mapped_column(Text)
    verification_method: Mapped[str | None] = mapped_column(String(255))
    verified_by: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    manual_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class RightsEvidence(TimestampMixin, Base):
    __tablename__ = "rights_evidence"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    rights_record_id: Mapped[int] = mapped_column(
        ForeignKey("rights_records.id", ondelete="CASCADE"), index=True
    )
    evidence_type: Mapped[str] = mapped_column(String(80))
    source_url: Mapped[str | None] = mapped_column(String(1500))
    local_path: Mapped[str | None] = mapped_column(String(1000))
    description: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str | None] = mapped_column(String(64))
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ImportJob(TimestampMixin, Base):
    __tablename__ = "import_jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    novel_id: Mapped[int | None] = mapped_column(ForeignKey("novels.id", ondelete="SET NULL"), index=True)
    job_type: Mapped[str] = mapped_column(String(80), default="INGEST")
    status: Mapped[str] = mapped_column(String(40), default=ImportStatus.DISCOVERED.value, index=True)
    checkpoint: Mapped[str | None] = mapped_column(String(100))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QualityIssue(TimestampMixin, Base):
    __tablename__ = "quality_issues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    novel_id: Mapped[int | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    import_job_id: Mapped[int | None] = mapped_column(
        ForeignKey("import_jobs.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(100), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    message: Mapped[str] = mapped_column(Text)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class NovelImage(TimestampMixin, Base):
    __tablename__ = "novel_images"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    image_type: Mapped[str] = mapped_column(String(40))
    path: Mapped[str] = mapped_column(String(1000))
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    mime_type: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    prompt_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ChapterImage(TimestampMixin, Base):
    __tablename__ = "chapter_images"
    __table_args__ = (
        UniqueConstraint(
            "chapter_id",
            "image_type",
            "placement_order",
            name="uq_chapter_images_placement",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    image_type: Mapped[str] = mapped_column(String(40), default="hero", nullable=False)
    placement_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    paragraph_anchor: Mapped[int | None] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(String(1000))
    fallback_path: Mapped[str | None] = mapped_column(String(1000))
    alt_text: Mapped[str] = mapped_column(String(500))
    generation_prompt: Mapped[str | None] = mapped_column(Text)
    generation_provider: Mapped[str | None] = mapped_column(String(120))
    generation_model: Mapped[str | None] = mapped_column(String(120))
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_status: Mapped[str] = mapped_column(
        String(40), default="ORIGINAL_GENERATED", nullable=False
    )
    width: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    height: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(100), default="image/webp", nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    animation_type: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    prompt_metadata: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ReadingProgress(TimestampMixin, Base):
    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", name="uq_reading_progress_user_novel"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    position_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ReadingHistory(TimestampMixin, Base):
    __tablename__ = "reading_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class Bookmark(TimestampMixin, Base):
    __tablename__ = "bookmarks"
    __table_args__ = (UniqueConstraint("user_id", "chapter_id", "position_key", name="uq_bookmark_position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chapter_id: Mapped[int] = mapped_column(ForeignKey("chapters.id", ondelete="CASCADE"), index=True)
    position_key: Mapped[str] = mapped_column(String(120), default="chapter")
    note: Mapped[str | None] = mapped_column(Text)


class UserLibrary(TimestampMixin, Base):
    __tablename__ = "user_library"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    status: Mapped[str] = mapped_column(String(30), default="SAVED")
    favourite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Rating(TimestampMixin, Base):
    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "novel_id", name="uq_rating_user_novel"),
        CheckConstraint("score >= 1 AND score <= 5", name="ck_rating_score"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    score: Mapped[int] = mapped_column(Integer)


class Review(TimestampMixin, Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", name="uq_review_user_novel"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    title: Mapped[str | None] = mapped_column(String(255))
    body: Mapped[str] = mapped_column(Text)
    contains_spoilers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    source_novel_id: Mapped[int | None] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"))
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), index=True)
    score: Mapped[Decimal] = mapped_column(Numeric(8, 6), default=0)
    reason: Mapped[str] = mapped_column(String(500))
    algorithm_version: Mapped[str] = mapped_column(String(50))


class TakedownRequest(TimestampMixin, Base):
    __tablename__ = "takedown_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    novel_id: Mapped[int | None] = mapped_column(ForeignKey("novels.id", ondelete="SET NULL"), index=True)
    requester_name: Mapped[str] = mapped_column(String(255))
    requester_email: Mapped[str] = mapped_column(String(320))
    claim: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default=TakedownStatus.RECEIVED.value, index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactRequest(TimestampMixin, Base):
    __tablename__ = "contact_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    requester_name: Mapped[str] = mapped_column(String(255))
    requester_email: Mapped[str] = mapped_column(String(320))
    category: Mapped[str] = mapped_column(String(80), index=True)
    message: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(40), default="RECEIVED", nullable=False, index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_type: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str | None] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(120), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    ip_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AnalyticsEvent(Base):
    __tablename__ = "analytics_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_name: Mapped[str] = mapped_column(String(80), index=True)
    anonymous_id: Mapped[str | None] = mapped_column(String(100), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    novel_id: Mapped[int | None] = mapped_column(ForeignKey("novels.id", ondelete="SET NULL"), index=True)
    chapter_id: Mapped[int | None] = mapped_column(ForeignKey("chapters.id", ondelete="SET NULL"))
    properties: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    consent_granted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class EditorialCollection(TimestampMixin, Base):
    __tablename__ = "editorial_collections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    slug: Mapped[str] = mapped_column(String(220), unique=True)
    title: Mapped[str] = mapped_column(String(500))
    introduction: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seo_description: Mapped[str | None] = mapped_column(String(320))


class CollectionItem(Base):
    __tablename__ = "collection_items"

    collection_id: Mapped[int] = mapped_column(
        ForeignKey("editorial_collections.id", ondelete="CASCADE"), primary_key=True
    )
    novel_id: Mapped[int] = mapped_column(ForeignKey("novels.id", ondelete="CASCADE"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer)
    editorial_note: Mapped[str | None] = mapped_column(Text)
