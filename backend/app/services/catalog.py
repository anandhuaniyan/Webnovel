from __future__ import annotations

import math
from collections.abc import Sequence

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.enums import APPROVED_RIGHTS_STATUSES, CompletenessStatus
from app.models import Author, Genre, Novel, NovelGenre, RightsRecord
from app.schemas import AuthorSummary, GenreSummary, HomeResponse, NovelCard, NovelDetail, PaginatedNovels

APPROVED_VALUES = [status.value for status in APPROVED_RIGHTS_STATUSES]


def publication_filter() -> tuple:
    return (
        Novel.published.is_(True),
        Novel.merged_into_novel_id.is_(None),
        Novel.completeness_status == CompletenessStatus.COMPLETE.value,
        Novel.rights_status.in_(APPROVED_VALUES),
    )


def _asset_url(path: str | None) -> str | None:
    if not path:
        return None
    normalized = path.replace("\\", "/")
    if normalized.startswith("storage/"):
        normalized = normalized.removeprefix("storage/")
    return f"/media/{normalized.lstrip('/')}"


def card_for(db: Session, novel: Novel) -> NovelCard:
    author = db.get(Author, novel.primary_author_id) if novel.primary_author_id else None
    genres = (
        db.execute(
            select(Genre)
            .join(NovelGenre, NovelGenre.genre_id == Genre.id)
            .where(NovelGenre.novel_id == novel.id)
            .order_by(NovelGenre.is_primary.desc(), Genre.name)
        )
        .scalars()
        .all()
    )
    return NovelCard(
        id=novel.id,
        slug=novel.slug,
        title=novel.title,
        author=AuthorSummary.model_validate(author) if author else None,
        genres=[GenreSummary.model_validate(genre) for genre in genres],
        description=novel.description,
        cover_url=_asset_url(novel.cover_path),
        thumbnail_url=_asset_url(novel.thumbnail_path or novel.cover_path),
        chapter_count=novel.chapter_count,
        total_words=novel.total_words,
        estimated_reading_minutes=novel.estimated_reading_minutes,
        average_rating=novel.average_rating,
        rating_count=novel.rating_count,
        published_at=novel.published_at,
    )


def detail_for(db: Session, novel: Novel) -> NovelDetail:
    card = card_for(db, novel)
    rights = db.scalar(
        select(RightsRecord)
        .where(RightsRecord.edition_id == novel.edition_id)
        .order_by(RightsRecord.updated_at.desc())
        .limit(1)
    )
    return NovelDetail(
        **card.model_dump(),
        alternative_title=novel.alternative_title,
        synopsis=novel.ai_synopsis,
        themes=novel.themes,
        setting=novel.setting,
        character_guide=novel.character_guide,
        literary_context=novel.literary_context,
        reading_difficulty=novel.reading_difficulty,
        language=novel.language,
        content_type=novel.content_type,
        completeness_status=novel.completeness_status,
        rights_status=novel.rights_status,
        rights_summary=(
            {
                "status": rights.status,
                "jurisdiction": rights.jurisdiction,
                "licence_name": rights.licence_name,
                "licence_url": rights.licence_url,
                "attribution": rights.attribution_text,
                "verified_at": rights.verified_at,
                "next_review_at": rights.next_review_at,
            }
            if rights
            else None
        ),
    )


def paginated_novels(db: Session, statement: Select, *, page: int, page_size: int) -> PaginatedNovels:
    page = max(1, page)
    page_size = min(100, max(1, page_size))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    items = db.scalars(statement.offset((page - 1) * page_size).limit(page_size)).all()
    return PaginatedNovels(
        items=[card_for(db, novel) for novel in items],
        page=page,
        page_size=page_size,
        total=total,
        pages=math.ceil(total / page_size) if total else 0,
    )


def _cards(db: Session, statement: Select, limit: int = 12) -> list[NovelCard]:
    novels: Sequence[Novel] = db.scalars(statement.limit(limit)).all()
    return [card_for(db, novel) for novel in novels]


def home_data(db: Session) -> HomeResponse:
    base = select(Novel).where(*publication_filter())
    recently_added = _cards(db, base.order_by(Novel.published_at.desc(), Novel.id.desc()))
    popular = _cards(db, base.order_by(Novel.view_count.desc(), Novel.published_at.desc()))
    highest_rated = _cards(
        db,
        base.where(Novel.rating_count > 0).order_by(Novel.average_rating.desc(), Novel.rating_count.desc()),
    )
    featured = _cards(db, base.where(Novel.featured.is_(True)).order_by(Novel.published_at.desc()), 6)
    short_reads = _cards(db, base.where(Novel.total_words <= 40_000).order_by(Novel.total_words.asc()))
    long_reads = _cards(db, base.where(Novel.total_words >= 120_000).order_by(Novel.total_words.desc()))
    genre_map: dict[str, list[NovelCard]] = {}
    for genre_slug in (
        "fantasy",
        "romance",
        "mystery",
        "adventure",
        "horror",
        "science-fiction",
        "historical-fiction",
        "crime",
    ):
        statement = (
            base.join(NovelGenre, NovelGenre.novel_id == Novel.id)
            .join(Genre, Genre.id == NovelGenre.genre_id)
            .where(Genre.slug == genre_slug)
            .order_by(Novel.published_at.desc())
        )
        genre_map[genre_slug.replace("-", "_")] = _cards(db, statement, 12)
    return HomeResponse(
        featured=featured,
        popular=popular,
        trending=popular,
        recently_added=recently_added,
        highest_rated=highest_rated,
        short_reads=short_reads,
        long_reads=long_reads,
        genres=genre_map,
    )
