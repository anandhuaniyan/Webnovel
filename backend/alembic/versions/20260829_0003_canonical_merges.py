"""Add non-destructive canonical duplicate links.

Revision ID: 20260829_0003
Revises: 20260829_0002
Create Date: 2026-08-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260829_0003"
down_revision = "20260829_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    work_columns = {column["name"] for column in inspector.get_columns("works")}
    if "canonical_work_id" not in work_columns:
        op.add_column("works", sa.Column("canonical_work_id", sa.BigInteger(), nullable=True))
        op.create_index("ix_works_canonical_work_id", "works", ["canonical_work_id"])
        op.create_foreign_key(
            "fk_works_canonical_work_id_works",
            "works",
            "works",
            ["canonical_work_id"],
            ["id"],
            ondelete="SET NULL",
        )

    novel_columns = {column["name"] for column in sa.inspect(bind).get_columns("novels")}
    if "merged_into_novel_id" not in novel_columns:
        op.add_column("novels", sa.Column("merged_into_novel_id", sa.BigInteger(), nullable=True))
        op.create_index("ix_novels_merged_into_novel_id", "novels", ["merged_into_novel_id"])
        op.create_foreign_key(
            "fk_novels_merged_into_novel_id_novels",
            "novels",
            "novels",
            ["merged_into_novel_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    bind = op.get_bind()
    novel_columns = {column["name"] for column in sa.inspect(bind).get_columns("novels")}
    if "merged_into_novel_id" in novel_columns:
        op.drop_constraint("fk_novels_merged_into_novel_id_novels", "novels", type_="foreignkey")
        op.drop_index("ix_novels_merged_into_novel_id", table_name="novels")
        op.drop_column("novels", "merged_into_novel_id")

    work_columns = {column["name"] for column in sa.inspect(bind).get_columns("works")}
    if "canonical_work_id" in work_columns:
        op.drop_constraint("fk_works_canonical_work_id_works", "works", type_="foreignkey")
        op.drop_index("ix_works_canonical_work_id", table_name="works")
        op.drop_column("works", "canonical_work_id")
