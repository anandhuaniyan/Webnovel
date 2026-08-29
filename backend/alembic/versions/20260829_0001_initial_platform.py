"""Create the isolated Webnovel platform schema.

Revision ID: 20260829_0001
Revises:
Create Date: 2026-08-29
"""

from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op
from app import models  # noqa: F401
from app.core.database import Base

revision = "20260829_0001"
down_revision = None
branch_labels = None
depends_on = None


GENRES = [
    "Fantasy",
    "Adventure",
    "Romance",
    "Mystery",
    "Detective",
    "Crime",
    "Horror",
    "Gothic",
    "Science Fiction",
    "Historical Fiction",
    "War",
    "Western",
    "Supernatural",
    "Mythology",
    "Drama",
    "Humour",
    "Satire",
    "Coming of Age",
    "Classic Literature",
]


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    Base.metadata.create_all(bind=bind)

    genre_table = sa.table(
        "genres",
        sa.column("slug", sa.String),
        sa.column("name", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        genre_table,
        [
            {
                "slug": name.lower().replace(" ", "-"),
                "name": name,
                "created_at": now,
                "updated_at": now,
            }
            for name in GENRES
        ],
    )

    source_table = sa.table(
        "sources",
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("base_url", sa.String),
        sa.column("adapter", sa.String),
        sa.column("enabled", sa.Boolean),
        sa.column("trust_score", sa.Integer),
        sa.column("terms_url", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        source_table,
        [
            {
                "code": "gutenberg",
                "name": "Project Gutenberg",
                "base_url": "https://www.gutenberg.org",
                "adapter": "gutenberg",
                "enabled": True,
                "trust_score": 75,
                "terms_url": "https://www.gutenberg.org/policy/permission.html",
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "standard_ebooks",
                "name": "Standard Ebooks",
                "base_url": "https://standardebooks.org",
                "adapter": "standard_ebooks",
                "enabled": True,
                "trust_score": 90,
                "terms_url": "https://standardebooks.org/about/uncopyright",
                "created_at": now,
                "updated_at": now,
            },
            {
                "code": "wikisource",
                "name": "Wikisource",
                "base_url": "https://en.wikisource.org",
                "adapter": "wikisource",
                "enabled": True,
                "trust_score": 70,
                "terms_url": "https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use",
                "created_at": now,
                "updated_at": now,
            },
        ],
    )


def downgrade() -> None:
    Base.metadata.drop_all(bind=op.get_bind())
