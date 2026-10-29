"""users, and who reported each report

Revision ID: e1a7b3c9d5f2
Revises: d0f6a2c7e4b5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e1a7b3c9d5f2"
down_revision: Union[str, Sequence[str], None] = "d0f6a2c7e4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=254), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="citizen", nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.add_column("reports", sa.Column("reporter_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_reports_reporter", "reports", "users", ["reporter_id"], ["id"], ondelete="SET NULL")
    # "My reports" lists one person's reports newest first; only rows that have a reporter.
    op.create_index(
        "ix_reports_reporter_created",
        "reports",
        ["reporter_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("reporter_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_reports_reporter_created", table_name="reports")
    op.drop_constraint("fk_reports_reporter", "reports", type_="foreignkey")
    op.drop_column("reports", "reporter_id")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
