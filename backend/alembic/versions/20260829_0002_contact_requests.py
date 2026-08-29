"""Add the tracked contact workflow.

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29
"""

import sqlalchemy as sa

from alembic import op

revision = "20260829_0002"
down_revision = "20260829_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The initial platform migration creates the current metadata on a fresh
    # install. Deployed 0001 databases still need this table, while a database
    # migrated from scratch will already have it.
    if "contact_requests" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "contact_requests",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("requester_name", sa.String(length=255), nullable=False),
        sa.Column("requester_email", sa.String(length=320), nullable=False),
        sa.Column("category", sa.String(length=80), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="RECEIVED"),
        sa.Column("resolution", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_contact_requests_category", "contact_requests", ["category"])
    op.create_index("ix_contact_requests_status", "contact_requests", ["status"])


def downgrade() -> None:
    if "contact_requests" not in sa.inspect(op.get_bind()).get_table_names():
        return
    op.drop_index("ix_contact_requests_status", table_name="contact_requests")
    op.drop_index("ix_contact_requests_category", table_name="contact_requests")
    op.drop_table("contact_requests")
