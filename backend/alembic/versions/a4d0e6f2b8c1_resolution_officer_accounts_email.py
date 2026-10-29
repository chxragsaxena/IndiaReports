"""resolution lifecycle, officer sign-in accounts, email queue

Revision ID: a4d0e6f2b8c1
Revises: f2b8c4d0a6e3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4d0e6f2b8c1"
down_revision: Union[str, Sequence[str], None] = "f2b8c4d0a6e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("reports", sa.Column("resolution_note", sa.Text(), nullable=True))
    op.add_column("reports", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_reports_resolved_by", "reports", "users", ["resolved_by"], ["id"], ondelete="SET NULL")

    # Reports resolved before this existed start their visibility window now, instead of
    # vanishing from the map the moment this migration runs.
    op.execute("UPDATE reports SET resolved_at = now() WHERE status = 'RESOLVED'")

    # The sweeper looks only at resolved reports that are still on the map.
    op.create_index(
        "ix_reports_resolved_on_map",
        "reports",
        ["resolved_at"],
        postgresql_where=sa.text("status = 'RESOLVED' AND archived_at IS NULL"),
    )

    op.add_column("officers", sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_officers_user", "officers", "users", ["user_id"], ["id"], ondelete="SET NULL")
    op.alter_column("officers", "telegram_chat_id", existing_type=sa.String(length=64), nullable=True)
    op.create_index(
        "uq_officers_user", "officers", ["user_id"], unique=True, postgresql_where=sa.text("user_id IS NOT NULL")
    )

    op.create_table(
        "email_jobs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("to_email", sa.String(length=254), nullable=False),
        sa.Column("subject", sa.String(length=200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index(
        "ix_email_jobs_due", "email_jobs", ["next_attempt_at"], postgresql_where=sa.text("sent_at IS NULL")
    )


def downgrade() -> None:
    op.drop_index("ix_email_jobs_due", table_name="email_jobs")
    op.drop_table("email_jobs")
    op.drop_index("uq_officers_user", table_name="officers")
    op.execute("UPDATE officers SET telegram_chat_id = '' WHERE telegram_chat_id IS NULL")
    op.alter_column("officers", "telegram_chat_id", existing_type=sa.String(length=64), nullable=False)
    op.drop_constraint("fk_officers_user", "officers", type_="foreignkey")
    op.drop_column("officers", "user_id")
    op.drop_index("ix_reports_resolved_on_map", table_name="reports")
    op.drop_constraint("fk_reports_resolved_by", "reports", type_="foreignkey")
    for column in ("archived_at", "confirmed_at", "resolution_note", "resolved_by", "resolved_at"):
        op.drop_column("reports", column)
