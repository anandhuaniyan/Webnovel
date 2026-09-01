"""Separate supporting research from private human rights approval.

Revision ID: 20260902_0005
Revises: 20260901_0004
Create Date: 2026-09-02
"""

import sqlalchemy as sa

from alembic import op

revision = "20260902_0005"
down_revision = "20260901_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rights_reviewers",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("reviewer_type", sa.String(length=40), nullable=False, server_default="INTERNAL"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "reviewer_type IN ('INTERNAL', 'EXTERNAL')",
            name="ck_rights_reviewers_type",
        ),
    )

    op.add_column("rights_records", sa.Column("research_method", sa.String(length=120)))
    op.add_column("rights_records", sa.Column("research_provider", sa.String(length=120)))
    op.add_column("rights_records", sa.Column("research_summary", sa.Text()))
    op.add_column("rights_records", sa.Column("research_completed_at", sa.DateTime(timezone=True)))
    op.add_column(
        "rights_records",
        sa.Column("human_review_required", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "rights_records",
        sa.Column("human_review_status", sa.String(length=40), nullable=False, server_default="PENDING"),
    )
    op.add_column("rights_records", sa.Column("reviewer_id", sa.BigInteger()))
    op.add_column("rights_records", sa.Column("review_reference", sa.String(length=80)))
    op.add_column(
        "rights_records",
        sa.Column("reviewer_visibility", sa.String(length=20), nullable=False, server_default="PRIVATE"),
    )
    op.create_foreign_key(
        "fk_rights_records_reviewer_id",
        "rights_records",
        "rights_reviewers",
        ["reviewer_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_rights_records_reviewer_id", "rights_records", ["reviewer_id"])
    op.create_index(
        "ix_rights_records_review_reference",
        "rights_records",
        ["review_reference"],
        unique=True,
    )
    op.create_check_constraint(
        "ck_rights_records_human_review_status",
        "rights_records",
        "human_review_status IN ('PENDING', 'APPROVED', 'NEEDS_LEGAL_REVIEW', 'REJECTED')",
    )
    op.create_check_constraint(
        "ck_rights_records_reviewer_visibility",
        "rights_records",
        "reviewer_visibility = 'PRIVATE'",
    )
    op.execute(
        """
        UPDATE rights_records
        SET human_review_status = CASE WHEN manual_approval THEN 'APPROVED' ELSE 'PENDING' END,
            review_reference = 'RIGHTS-' || EXTRACT(YEAR FROM created_at)::integer || '-' || LPAD(id::text, 5, '0'),
            reviewer_visibility = 'PRIVATE'
        """
    )


def downgrade() -> None:
    op.drop_constraint("ck_rights_records_reviewer_visibility", "rights_records", type_="check")
    op.drop_constraint("ck_rights_records_human_review_status", "rights_records", type_="check")
    op.drop_index("ix_rights_records_review_reference", table_name="rights_records")
    op.drop_index("ix_rights_records_reviewer_id", table_name="rights_records")
    op.drop_constraint("fk_rights_records_reviewer_id", "rights_records", type_="foreignkey")
    for column in (
        "reviewer_visibility",
        "review_reference",
        "reviewer_id",
        "human_review_status",
        "human_review_required",
        "research_completed_at",
        "research_summary",
        "research_provider",
        "research_method",
    ):
        op.drop_column("rights_records", column)
    op.drop_table("rights_reviewers")
