from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.enums import APPROVED_RIGHTS_STATUSES
from app.models import (
    AnalyticsEvent,
    Author,
    Chapter,
    Genre,
    Novel,
    NovelGenre,
    Review,
    TakedownRequest,
    User,
)
from app.schemas import (
    AnalyticsEventCreate,
    AuthorSummary,
    ChapterDetail,
    ChapterSummary,
    GenreSummary,
    HomeResponse,
    NovelCard,
    NovelDetail,
    PaginatedNovels,
    TakedownCreate,
)
from app.services.catalog import card_for, detail_for, home_data, paginated_novels, publication_filter
from app.services.search import SearchService

router = APIRouter(prefix="/api", tags=["public"])
APPROVED_VALUES = [status.value for status in APPROVED_RIGHTS_STATUSES]


@router.get("/home", response_model=HomeResponse)
def home(db: Session = Depends(get_db)) -> HomeResponse:
    return home_data(db)


@router.get("/catalogue/stats")
def catalogue_stats(db: Session = Depends(get_db)) -> dict:
    published_ids = select(Novel.id).where(*publication_filter())
    return {
        "novels": db.scalar(select(func.count()).select_from(published_ids.subquery())) or 0,
        "chapters": db.scalar(
            select(func.coalesce(func.sum(Novel.chapter_count), 0)).where(*publication_filter())
        )
        or 0,
        "genres": db.scalar(
            select(func.count(func.distinct(NovelGenre.genre_id))).where(
                NovelGenre.novel_id.in_(published_ids)
            )
        )
        or 0,
    }


@router.get("/novels", response_model=PaginatedNovels)
def novels(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=100),
    genre: str | None = None,
    author: str | None = None,
    sort: str = Query(default="recent", pattern="^(recent|title|rating|length)$"),
    db: Session = Depends(get_db),
) -> PaginatedNovels:
    statement = select(Novel).where(*publication_filter())
    if genre:
        statement = (
            statement.join(NovelGenre, NovelGenre.novel_id == Novel.id).join(Genre).where(Genre.slug == genre)
        )
    if author:
        statement = statement.join(Author, Author.id == Novel.primary_author_id).where(Author.slug == author)
    ordering = {
        "recent": (Novel.published_at.desc(), Novel.id.desc()),
        "title": (Novel.title.asc(),),
        "rating": (Novel.average_rating.desc(), Novel.rating_count.desc()),
        "length": (Novel.total_words.asc(),),
    }
    statement = statement.order_by(*ordering[sort])
    return paginated_novels(db, statement, page=page, page_size=page_size)


def _published_novel_or_404(db: Session, slug: str) -> Novel:
    novel = db.scalar(select(Novel).where(Novel.slug == slug, *publication_filter()))
    if not novel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
    return novel


@router.get("/novels/{slug}", response_model=NovelDetail)
def novel_detail(slug: str, db: Session = Depends(get_db)) -> NovelDetail:
    return detail_for(db, _published_novel_or_404(db, slug))


@router.get("/novels/{slug}/chapters", response_model=list[ChapterSummary])
def novel_chapters(slug: str, db: Session = Depends(get_db)) -> list[ChapterSummary]:
    novel = _published_novel_or_404(db, slug)
    chapters = db.scalars(
        select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.chapter_order)
    ).all()
    return [ChapterSummary.model_validate(chapter) for chapter in chapters]


@router.get("/novels/{slug}/chapters/{chapter_slug}", response_model=ChapterDetail)
def novel_chapter(slug: str, chapter_slug: str, db: Session = Depends(get_db)) -> ChapterDetail:
    novel = _published_novel_or_404(db, slug)
    chapter = db.scalar(
        select(Chapter).where(Chapter.novel_id == novel.id, Chapter.chapter_slug == chapter_slug)
    )

    if not chapter:
        raise HTTPException(status_code=404, detail="Chapter not found")
    previous = db.scalar(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.chapter_order < chapter.chapter_order)
        .order_by(Chapter.chapter_order.desc())
        .limit(1)
    )
    next_chapter = db.scalar(
        select(Chapter)
        .where(Chapter.novel_id == novel.id, Chapter.chapter_order > chapter.chapter_order)
        .order_by(Chapter.chapter_order)
        .limit(1)
    )
    return ChapterDetail(
        **ChapterSummary.model_validate(chapter).model_dump(),
        novel_slug=novel.slug,
        novel_title=novel.title,
        content_html=chapter.content_html,
        previous_chapter=ChapterSummary.model_validate(previous) if previous else None,
        next_chapter=ChapterSummary.model_validate(next_chapter) if next_chapter else None,
    )


@router.get("/novels/{slug}/reviews")
def novel_reviews(
    slug: str, limit: int = Query(default=30, ge=1, le=100), db: Session = Depends(get_db)
) -> list[dict]:
    novel = _published_novel_or_404(db, slug)
    rows = db.execute(
        select(Review, User)
        .join(User, User.id == Review.user_id)
        .where(Review.novel_id == novel.id, Review.approved.is_(True))
        .order_by(Review.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": review.id,
            "display_name": user.display_name,
            "title": review.title,
            "body": review.body,
            "contains_spoilers": review.contains_spoilers,
            "created_at": review.created_at,
        }
        for review, user in rows
    ]


@router.get("/authors", response_model=list[AuthorSummary])
def authors(db: Session = Depends(get_db)) -> list[AuthorSummary]:
    items = db.scalars(
        select(Author)
        .join(Novel, Novel.primary_author_id == Author.id)
        .where(*publication_filter())
        .distinct()
        .order_by(Author.name)
    ).all()
    return [AuthorSummary.model_validate(item) for item in items]


@router.get("/authors/{slug}")
def author_detail(slug: str, db: Session = Depends(get_db)) -> dict:
    author = db.scalar(select(Author).where(Author.slug == slug))
    if not author:
        raise HTTPException(status_code=404, detail="Author not found")
    works = db.scalars(
        select(Novel).where(Novel.primary_author_id == author.id, *publication_filter()).order_by(Novel.title)
    ).all()
    if not works:
        raise HTTPException(status_code=404, detail="Author not found")
    return {
        "id": author.id,
        "slug": author.slug,
        "name": author.name,
        "biography": author.biography,
        "birth_date": author.birth_date,
        "death_date": author.death_date,
        "death_year": author.death_year,
        "country": author.country,
        "works": [card_for(db, novel) for novel in works],
    }


@router.get("/genres", response_model=list[GenreSummary])
def genres(db: Session = Depends(get_db)) -> list[GenreSummary]:
    items = db.scalars(select(Genre).order_by(Genre.name)).all()
    return [GenreSummary.model_validate(item) for item in items]


@router.get("/genres/{slug}")
def genre_detail(slug: str, db: Session = Depends(get_db)) -> dict:
    genre = db.scalar(select(Genre).where(Genre.slug == slug))
    if not genre:
        raise HTTPException(status_code=404, detail="Genre not found")
    works = db.scalars(
        select(Novel)
        .join(NovelGenre, NovelGenre.novel_id == Novel.id)
        .where(NovelGenre.genre_id == genre.id, *publication_filter())
        .order_by(Novel.published_at.desc())
        .limit(50)
    ).all()
    authors_rows = db.scalars(
        select(Author)
        .join(Novel, Novel.primary_author_id == Author.id)
        .join(NovelGenre, NovelGenre.novel_id == Novel.id)
        .where(NovelGenre.genre_id == genre.id, *publication_filter())
        .distinct()
        .limit(20)
    ).all()
    return {
        "id": genre.id,
        "slug": genre.slug,
        "name": genre.name,
        "introduction": genre.introduction,
        "novels": [card_for(db, novel) for novel in works],
        "authors": [AuthorSummary.model_validate(author) for author in authors_rows],
    }


@router.get("/search", response_model=list[NovelCard])
def search(
    q: str = Query(min_length=2, max_length=200), limit: int = 30, db: Session = Depends(get_db)
) -> list[NovelCard]:
    return SearchService().search(db, q, limit)


@router.get("/recommendations", response_model=list[NovelCard])
def recommendations(
    novel_slug: str | None = None, limit: int = 12, db: Session = Depends(get_db)
) -> list[NovelCard]:
    limit = min(max(limit, 1), 50)
    if novel_slug:
        source_novel = _published_novel_or_404(db, novel_slug)
        genre_ids = select(NovelGenre.genre_id).where(NovelGenre.novel_id == source_novel.id)
        statement = (
            select(Novel)
            .join(NovelGenre, NovelGenre.novel_id == Novel.id)
            .where(NovelGenre.genre_id.in_(genre_ids), Novel.id != source_novel.id, *publication_filter())
            .group_by(Novel.id)
            .order_by(func.count(NovelGenre.genre_id).desc(), Novel.average_rating.desc())
            .limit(limit)
        )
    else:
        statement = (
            select(Novel)
            .where(*publication_filter())
            .order_by(Novel.average_rating.desc(), Novel.published_at.desc())
            .limit(limit)
        )
    return [card_for(db, novel) for novel in db.scalars(statement).all()]


@router.get("/config/public")
def public_config() -> dict:
    from app.core.config import get_settings

    settings = get_settings()
    return {
        "adsense_enabled": settings.adsense_enabled and bool(settings.adsense_client_id),
        "adsense_client_id": settings.adsense_client_id if settings.adsense_enabled else "",
        "adsense_auto_ads": settings.adsense_auto_ads if settings.adsense_enabled else False,
        "ga_measurement_id": settings.ga_measurement_id,
        "consent_provider": settings.consent_provider,
    }


@router.post("/analytics/events", status_code=202)
def analytics_event(payload: AnalyticsEventCreate, db: Session = Depends(get_db)) -> dict:
    if not payload.consent_granted:
        return {"accepted": False, "reason": "analytics consent not granted"}
    event = AnalyticsEvent(**payload.model_dump())
    db.add(event)
    db.commit()
    return {"accepted": True}


@router.post("/takedown", status_code=201)
def submit_takedown(payload: TakedownCreate, db: Session = Depends(get_db)) -> dict:
    novel_id = None
    if payload.novel_slug:
        novel_id = db.scalar(select(Novel.id).where(Novel.slug == payload.novel_slug))
    request = TakedownRequest(
        novel_id=novel_id,
        requester_name=payload.requester_name,
        requester_email=str(payload.requester_email),
        claim=payload.claim,
        evidence=payload.evidence,
    )
    db.add(request)
    db.commit()
    return {"id": request.id, "status": request.status, "received_at": request.created_at}
