"""voice notes: a spoken description of a report, and its transcript

Revision ID: f9c5d1e7a3b6
Revises: e8b4c0d6f2a5
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f9c5d1e7a3b6"
down_revision: Union[str, Sequence[str], None] = "e8b4c0d6f2a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_voice_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id", ondelete="CASCADE"), nullable=False),
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_key", sa.String(300), nullable=False),
        sa.Column("content_type", sa.String(50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("language", sa.String(40), nullable=True),
        sa.Column("provider", sa.String(20), nullable=True),
        sa.Column("model", sa.String(80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("transcribed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_report_voice_notes_report", "report_voice_notes", ["report_id"])


def downgrade() -> None:
    op.drop_index("ix_report_voice_notes_report", table_name="report_voice_notes")
    op.drop_table("report_voice_notes")
