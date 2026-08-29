from __future__ import annotations

from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.models import Author, Genre, Novel, NovelGenre, NovelTag, Tag
from app.schemas import NovelCard
from app.services.catalog import card_for, publication_filter


class SearchService:
    def search(self, db: Session, query: str, limit: int = 30) -> list[NovelCard]:
        query = " ".join(query.split()).strip()
        if not query:
            return []
        ts_query = func.websearch_to_tsquery("english", query)
        rank = func.ts_rank_cd(Novel.search_vector, ts_query)
        similarity = func.greatest(
            func.similarity(Novel.title, query),
            func.similarity(func.coalesce(Novel.alternative_title, ""), query),
            func.similarity(func.coalesce(Author.name, ""), query),
        )
        statement = (
            select(Novel)
            .outerjoin(Author, Author.id == Novel.primary_author_id)
            .outerjoin(NovelGenre, NovelGenre.novel_id == Novel.id)
            .outerjoin(Genre, Genre.id == NovelGenre.genre_id)
            .outerjoin(NovelTag, NovelTag.novel_id == Novel.id)
            .outerjoin(Tag, Tag.id == NovelTag.tag_id)
            .where(
                *publication_filter(),
                or_(
                    Novel.search_vector.op("@@")(ts_query),
                    similarity > 0.18,
                    Genre.name.ilike(f"%{query}%"),
                    Tag.name.ilike(f"%{query}%"),
                ),
            )
            .group_by(Novel.id, Author.name)
            .order_by(desc(rank + similarity), Novel.title)
            .limit(min(max(limit, 1), 100))
        )
        return [card_for(db, novel) for novel in db.scalars(statement).all()]
