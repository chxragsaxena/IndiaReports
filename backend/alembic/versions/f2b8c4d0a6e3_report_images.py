"""report_images: photos on reports and their AI findings

Revision ID: f2b8c4d0a6e3
Revises: e1a7b3c9d5f2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f2b8c4d0a6e3"
down_revision: Union[str, Sequence[str], None] = "e1a7b3c9d5f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "report_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("report_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploader_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("storage_key", sa.String(length=300), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=True),
        sa.Column("analysis", postgresql.JSONB(), nullable=True),
        sa.Column("analysis_provider", sa.String(length=20), nullable=True),
        sa.Column("analysis_model", sa.String(length=80), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("analyzed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["report_id"], ["reports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_images_report", "report_images", ["report_id"])
    op.create_index("ix_report_images_analyzed_at", "report_images", ["analyzed_at"])
    # The worker only ever looks at unfinished rows, so index just those.
    op.create_index(
        "ix_report_images_work",
        "report_images",
        ["next_attempt_at"],
        postgresql_where=sa.text("status IN ('pending', 'analyzing')"),
    )


def downgrade() -> None:
    op.drop_index("ix_report_images_work", table_name="report_images")
    op.drop_index("ix_report_images_analyzed_at", table_name="report_images")
    op.drop_index("ix_report_images_report", table_name="report_images")
    op.drop_table("report_images")
