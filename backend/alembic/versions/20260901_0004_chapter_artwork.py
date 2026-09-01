"""Add chapter artwork placements and per-novel visual profiles.

Revision ID: 20260901_0004
Revises: 20260829_0003
Create Date: 2026-09-01
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260901_0004"
down_revision = "20260829_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "novel_visual_profiles" not in tables:
        op.create_table(
            "novel_visual_profiles",
            sa.Column("id", sa.BigInteger(), primary_key=True),
            sa.Column(
                "novel_id",
                sa.BigInteger(),
                sa.ForeignKey("novels.id", ondelete="CASCADE"),
                nullable=False,
                unique=True,
            ),
            sa.Column("historical_period", sa.String(length=255), nullable=True),
            sa.Column(
                "environments",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "recurring_characters",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("atmosphere", sa.String(length=500), nullable=True),
            sa.Column(
                "illustration_style",
                sa.String(length=255),
                nullable=False,
                server_default="cinematic editorial storybook illustration",
            ),
            sa.Column(
                "lighting_style",
                sa.String(length=255),
                nullable=False,
                server_default="naturalistic period-appropriate light",
            ),
            sa.Column(
                "color_palette",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "visual_motifs",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "prompt_constraints",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
        op.create_index(
            "ix_novel_visual_profiles_novel_id",
            "novel_visual_profiles",
            ["novel_id"],
            unique=True,
        )

    existing = {column["name"] for column in sa.inspect(bind).get_columns("chapter_images")}
    additions = [
        ("image_type", sa.Column("image_type", sa.String(length=40), nullable=False, server_default="hero")),
        ("placement_order", sa.Column("placement_order", sa.Integer(), nullable=False, server_default="0")),
        ("paragraph_anchor", sa.Column("paragraph_anchor", sa.Integer(), nullable=True)),
        ("fallback_path", sa.Column("fallback_path", sa.String(length=1000), nullable=True)),
        ("generation_prompt", sa.Column("generation_prompt", sa.Text(), nullable=True)),
        ("generation_provider", sa.Column("generation_provider", sa.String(length=120), nullable=True)),
        ("generation_model", sa.Column("generation_model", sa.String(length=120), nullable=True)),
        ("generated_at", sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True)),
        (
            "source_status",
            sa.Column(
                "source_status", sa.String(length=40), nullable=False, server_default="ORIGINAL_GENERATED"
            ),
        ),
        ("width", sa.Column("width", sa.Integer(), nullable=False, server_default="0")),
        ("height", sa.Column("height", sa.Integer(), nullable=False, server_default="0")),
        (
            "mime_type",
            sa.Column("mime_type", sa.String(length=100), nullable=False, server_default="image/webp"),
        ),
        ("file_size", sa.Column("file_size", sa.BigInteger(), nullable=False, server_default="0")),
        (
            "animation_type",
            sa.Column("animation_type", sa.String(length=40), nullable=False, server_default="none"),
        ),
        (
            "prompt_metadata",
            sa.Column(
                "prompt_metadata",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        ),
    ]
    for name, column in additions:
        if name not in existing:
            op.add_column("chapter_images", column)

    inspector = sa.inspect(bind)
    unique_names = {
        constraint.get("name") for constraint in inspector.get_unique_constraints("chapter_images")
    }
    if "uq_chapter_images_placement" not in unique_names:
        op.create_unique_constraint(
            "uq_chapter_images_placement",
            "chapter_images",
            ["chapter_id", "image_type", "placement_order"],
        )
    index_names = {index.get("name") for index in inspector.get_indexes("chapter_images")}
    if "ix_chapter_images_approved" not in index_names:
        op.create_index("ix_chapter_images_approved", "chapter_images", ["approved"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    index_names = {index.get("name") for index in inspector.get_indexes("chapter_images")}
    if "ix_chapter_images_approved" in index_names:
        op.drop_index("ix_chapter_images_approved", table_name="chapter_images")
    unique_names = {
        constraint.get("name") for constraint in inspector.get_unique_constraints("chapter_images")
    }
    if "uq_chapter_images_placement" in unique_names:
        op.drop_constraint("uq_chapter_images_placement", "chapter_images", type_="unique")
    for name in [
        "prompt_metadata",
        "animation_type",
        "file_size",
        "mime_type",
        "height",
        "width",
        "source_status",
        "generated_at",
        "generation_model",
        "generation_provider",
        "generation_prompt",
        "fallback_path",
        "paragraph_anchor",
        "placement_order",
        "image_type",
    ]:
        if name in {column["name"] for column in sa.inspect(bind).get_columns("chapter_images")}:
            op.drop_column("chapter_images", name)
    if "novel_visual_profiles" in sa.inspect(bind).get_table_names():
        op.drop_index("ix_novel_visual_profiles_novel_id", table_name="novel_visual_profiles")
        op.drop_table("novel_visual_profiles")
