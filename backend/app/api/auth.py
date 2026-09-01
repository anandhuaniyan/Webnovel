from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, get_current_user, hash_password, verify_password
from app.models import (
    Bookmark,
    Chapter,
    Novel,
    Rating,
    ReadingHistory,
    ReadingProgress,
    Review,
    User,
    UserLibrary,
)
from app.schemas import (
    BookmarkCreate,
    LibraryUpdate,
    LoginRequest,
    ProgressUpdate,
    RatingUpdate,
    ReaderSettingsUpdate,
    ReadingHistoryCreate,
    RegisterRequest,
    ReviewCreate,
    TokenResponse,
)
from app.services.catalog import publication_filter

router = APIRouter(prefix="/api", tags=["accounts"])


@router.post("/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, db: Session = Depends(get_db)) -> TokenResponse:
    email = str(payload.email).lower()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="An account with this email already exists")
    user = User(email=email, password_hash=hash_password(payload.password), display_name=payload.display_name)
    db.add(user)
    db.commit()
    db.refresh(user)
    return TokenResponse(access_token=create_access_token(user))


@router.post("/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
    user = db.scalar(select(User).where(User.email == str(payload.email).lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
    return TokenResponse(access_token=create_access_token(user))


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "consent_preferences": user.consent_preferences,
        "reader_settings": user.reader_settings,
    }


@router.get("/me/library")
def library(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(UserLibrary, Novel)
        .join(Novel, Novel.id == UserLibrary.novel_id)
        .where(UserLibrary.user_id == user.id, *publication_filter())
        .order_by(UserLibrary.updated_at.desc())
    ).all()
    return [
        {
            "novel": {"id": novel.id, "slug": novel.slug, "title": novel.title},
            "status": item.status,
            "favourite": item.favourite,
        }
        for item, novel in rows
    ]


@router.put("/me/library/{novel_id}")
def update_library(
    novel_id: int,
    payload: LibraryUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    novel = db.scalar(select(Novel).where(Novel.id == novel_id, *publication_filter()))
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    item = db.get(UserLibrary, (user.id, novel_id))
    if item:
        item.status = payload.status
        item.favourite = payload.favourite
    else:
        item = UserLibrary(
            user_id=user.id, novel_id=novel_id, status=payload.status, favourite=payload.favourite
        )
        db.add(item)
    db.commit()
    return {"saved": True, "status": item.status, "favourite": item.favourite}


@router.delete("/me/library/{novel_id}", status_code=204)
def remove_library(
    novel_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    db.execute(delete(UserLibrary).where(UserLibrary.user_id == user.id, UserLibrary.novel_id == novel_id))
    db.commit()


@router.put("/me/progress/{novel_id}")
def update_progress(
    novel_id: int,
    payload: ProgressUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    if not db.scalar(select(Novel.id).where(Novel.id == novel_id, *publication_filter())):
        raise HTTPException(status_code=404, detail="Novel not found")
    if payload.chapter_id and not db.scalar(
        select(Chapter.id).where(Chapter.id == payload.chapter_id, Chapter.novel_id == novel_id)
    ):
        raise HTTPException(status_code=400, detail="Chapter does not belong to this novel")
    progress = db.scalar(
        select(ReadingProgress).where(
            ReadingProgress.user_id == user.id, ReadingProgress.novel_id == novel_id
        )
    )
    if not progress:
        progress = ReadingProgress(user_id=user.id, novel_id=novel_id)
        db.add(progress)
    progress.chapter_id = payload.chapter_id
    progress.position_percent = payload.position_percent
    progress.completed = payload.completed
    db.commit()
    return {"saved": True}


@router.post("/me/bookmarks", status_code=201)
def add_bookmark(
    payload: BookmarkCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    if not db.scalar(
        select(Chapter.id)
        .join(Novel, Novel.id == Chapter.novel_id)
        .where(Chapter.id == payload.chapter_id, *publication_filter())
    ):
        raise HTTPException(status_code=404, detail="Chapter not found")
    bookmark = db.scalar(
        select(Bookmark).where(
            Bookmark.user_id == user.id,
            Bookmark.chapter_id == payload.chapter_id,
            Bookmark.position_key == payload.position_key,
        )
    )
    if bookmark:
        bookmark.note = payload.note
    else:
        bookmark = Bookmark(user_id=user.id, **payload.model_dump())
        db.add(bookmark)
    db.commit()
    return {"id": bookmark.id, "saved": True}


@router.get("/me/bookmarks")
def bookmarks(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(Bookmark, Chapter, Novel)
        .join(Chapter, Chapter.id == Bookmark.chapter_id)
        .join(Novel, Novel.id == Chapter.novel_id)
        .where(Bookmark.user_id == user.id, *publication_filter())
        .order_by(Bookmark.updated_at.desc())
    ).all()
    return [
        {
            "id": bookmark.id,
            "position_key": bookmark.position_key,
            "note": bookmark.note,
            "novel": {"slug": novel.slug, "title": novel.title},
            "chapter": {"slug": chapter.chapter_slug, "title": chapter.chapter_title},
        }
        for bookmark, chapter, novel in rows
    ]


@router.delete("/me/bookmarks/{bookmark_id}", status_code=204)
def remove_bookmark(
    bookmark_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> None:
    db.execute(delete(Bookmark).where(Bookmark.id == bookmark_id, Bookmark.user_id == user.id))
    db.commit()


@router.post("/me/history", status_code=201)
def record_history(
    payload: ReadingHistoryCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    novel = db.scalar(select(Novel).where(Novel.id == payload.novel_id, *publication_filter()))
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    if payload.chapter_id and not db.scalar(
        select(Chapter.id).where(Chapter.id == payload.chapter_id, Chapter.novel_id == novel.id)
    ):
        raise HTTPException(status_code=400, detail="Chapter does not belong to this novel")
    event = ReadingHistory(user_id=user.id, novel_id=novel.id, chapter_id=payload.chapter_id)
    db.add(event)
    db.commit()
    return {"id": event.id, "recorded": True}


@router.get("/me/history")
def reading_history(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(ReadingHistory, Novel, Chapter)
        .join(Novel, Novel.id == ReadingHistory.novel_id)
        .outerjoin(Chapter, Chapter.id == ReadingHistory.chapter_id)
        .where(ReadingHistory.user_id == user.id, *publication_filter())
        .order_by(ReadingHistory.read_at.desc())
        .limit(200)
    ).all()
    return [
        {
            "read_at": item.read_at,
            "novel": {"slug": novel.slug, "title": novel.title},
            "chapter": {"slug": chapter.chapter_slug, "title": chapter.chapter_title} if chapter else None,
        }
        for item, novel, chapter in rows
    ]


@router.get("/me/continue-reading")
def continue_reading(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> list[dict]:
    rows = db.execute(
        select(ReadingProgress, Novel, Chapter)
        .join(Novel, Novel.id == ReadingProgress.novel_id)
        .outerjoin(Chapter, Chapter.id == ReadingProgress.chapter_id)
        .where(
            ReadingProgress.user_id == user.id, ReadingProgress.completed.is_(False), *publication_filter()
        )
        .order_by(ReadingProgress.updated_at.desc())
        .limit(30)
    ).all()
    return [
        {
            "novel": {"id": novel.id, "slug": novel.slug, "title": novel.title},
            "chapter": {"id": chapter.id, "slug": chapter.chapter_slug, "title": chapter.chapter_title}
            if chapter
            else None,
            "position_percent": progress.position_percent,
            "updated_at": progress.updated_at,
        }
        for progress, novel, chapter in rows
    ]


@router.put("/me/reader-settings")
def update_reader_settings(
    payload: ReaderSettingsUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> dict:
    user.reader_settings = payload.model_dump()
    db.commit()
    return user.reader_settings


@router.put("/me/ratings/{novel_id}")
def update_rating(
    novel_id: int,
    payload: RatingUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    novel = db.scalar(select(Novel).where(Novel.id == novel_id, *publication_filter()))
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    rating = db.scalar(select(Rating).where(Rating.user_id == user.id, Rating.novel_id == novel.id))
    if rating:
        rating.score = payload.score
    else:
        db.add(Rating(user_id=user.id, novel_id=novel.id, score=payload.score))
    db.flush()
    average, count = db.execute(
        select(func.avg(Rating.score), func.count(Rating.id)).where(Rating.novel_id == novel.id)
    ).one()
    novel.average_rating = average or 0
    novel.rating_count = count
    db.commit()
    return {
        "score": payload.score,
        "average_rating": novel.average_rating,
        "rating_count": novel.rating_count,
    }


@router.post("/me/reviews/{novel_id}", status_code=201)
def submit_review(
    novel_id: int,
    payload: ReviewCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    novel = db.scalar(select(Novel).where(Novel.id == novel_id, *publication_filter()))
    if not novel:
        raise HTTPException(status_code=404, detail="Novel not found")
    review = db.scalar(select(Review).where(Review.user_id == user.id, Review.novel_id == novel.id))
    if review:
        review.title = payload.title
        review.body = payload.body
        review.contains_spoilers = payload.contains_spoilers
        review.approved = False
    else:
        review = Review(user_id=user.id, novel_id=novel.id, approved=False, **payload.model_dump())
        db.add(review)
    db.commit()
    return {"id": review.id, "status": "PENDING_MODERATION"}
