"""duplicate detection: affected count, possible duplicate link, supporters ("me too")

Revision ID: c6f2a8b4d0e3
Revises: b5e1f7a3c9d2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c6f2a8b4d0e3"
down_revision: Union[str, Sequence[str], None] = "b5e1f7a3c9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("affected_count", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("reports", sa.Column("possible_duplicate_of", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_reports_possible_duplicate_of", "reports", "reports", ["possible_duplicate_of"], ["id"], ondelete="SET NULL"
    )
    op.create_table(
        "report_supporters",
        sa.Column("report_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("reports.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_report_supporters_user", "report_supporters", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_report_supporters_user", table_name="report_supporters")
    op.drop_table("report_supporters")
    op.drop_constraint("fk_reports_possible_duplicate_of", "reports", type_="foreignkey")
    op.drop_column("reports", "possible_duplicate_of")
    op.drop_column("reports", "affected_count")
