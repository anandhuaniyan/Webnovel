from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class AuthorSummary(BaseModel):
    id: int
    slug: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class GenreSummary(BaseModel):
    id: int
    slug: str
    name: str

    model_config = ConfigDict(from_attributes=True)


class NovelCard(BaseModel):
    id: int
    slug: str
    title: str
    author: AuthorSummary | None
    genres: list[GenreSummary] = []
    description: str | None = None
    cover_url: str | None = None
    thumbnail_url: str | None = None
    chapter_count: int
    total_words: int
    estimated_reading_minutes: int
    average_rating: Decimal
    rating_count: int
    published_at: datetime | None = None


class NovelDetail(NovelCard):
    alternative_title: str | None = None
    synopsis: str | None = None
    themes: str | None = None
    setting: str | None = None
    character_guide: str | None = None
    literary_context: str | None = None
    reading_difficulty: str | None = None
    language: str
    content_type: str
    completeness_status: str
    rights_status: str
    rights_summary: dict | None = None


class ChapterSummary(BaseModel):
    id: int
    chapter_number: int | None
    chapter_order: int
    chapter_title: str
    chapter_slug: str
    word_count: int
    estimated_reading_minutes: int

    model_config = ConfigDict(from_attributes=True)


class ChapterDetail(ChapterSummary):
    novel_slug: str
    novel_title: str
    content_html: str
    illustrations: list[dict] = []
    previous_chapter: ChapterSummary | None = None
    next_chapter: ChapterSummary | None = None


class PaginatedNovels(BaseModel):
    items: list[NovelCard]
    page: int
    page_size: int
    total: int
    pages: int


class HomeResponse(BaseModel):
    featured: list[NovelCard]
    popular: list[NovelCard]
    trending: list[NovelCard]
    recently_added: list[NovelCard]
    highest_rated: list[NovelCard]
    short_reads: list[NovelCard]
    long_reads: list[NovelCard]
    genres: dict[str, list[NovelCard]]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)
    display_name: str = Field(min_length=2, max_length=100)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ProgressUpdate(BaseModel):
    chapter_id: int | None = None
    position_percent: Decimal = Field(ge=0, le=100)
    completed: bool = False


class LibraryUpdate(BaseModel):
    status: str = Field(default="SAVED", pattern="^(SAVED|READING|COMPLETED)$")
    favourite: bool = False


class BookmarkCreate(BaseModel):
    chapter_id: int
    position_key: str = "chapter"
    note: str | None = Field(default=None, max_length=2000)


class ReadingHistoryCreate(BaseModel):
    novel_id: int
    chapter_id: int | None = None


class RatingUpdate(BaseModel):
    score: int = Field(ge=1, le=5)


class ReviewCreate(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    body: str = Field(min_length=20, max_length=10_000)
    contains_spoilers: bool = False


class ReaderSettingsUpdate(BaseModel):
    font_family: str = Field(default="serif", pattern="^(serif|sans-serif|dyslexic)$")
    font_scale: int = Field(default=100, ge=80, le=180)
    line_height: int = Field(default=185, ge=130, le=240)
    content_width: int = Field(default=760, ge=480, le=1100)
    theme: str = Field(default="paper", pattern="^(paper|light|dark|sepia)$")


class AnalyticsEventCreate(BaseModel):
    event_name: str = Field(
        pattern="^(novel_view|reading_started|chapter_view|chapter_completed|search|library_add|bookmark|novel_completed)$"
    )
    anonymous_id: str | None = Field(default=None, max_length=100)
    novel_id: int | None = None
    chapter_id: int | None = None
    properties: dict = {}
    consent_granted: bool


class TakedownCreate(BaseModel):
    novel_slug: str | None = None
    requester_name: str = Field(min_length=2, max_length=255)
    requester_email: EmailStr
    claim: str = Field(min_length=30, max_length=20_000)
    evidence: str | None = Field(default=None, max_length=20_000)
