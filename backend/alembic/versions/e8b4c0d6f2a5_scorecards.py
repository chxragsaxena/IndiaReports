"""scorecards: the area a report was routed to, and how often a fix was disputed

Revision ID: e8b4c0d6f2a5
Revises: d7a3b9c5e1f4
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e8b4c0d6f2a5"
down_revision: Union[str, Sequence[str], None] = "d7a3b9c5e1f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("area_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key("fk_reports_area_id", "reports", "areas", ["area_id"], ["id"], ondelete="SET NULL")
    op.add_column("reports", sa.Column("reopen_count", sa.Integer(), nullable=False, server_default="0"))
    # Existing reports: the smallest area that contains the point, the same rule routing uses.
    op.execute(
        """
        UPDATE reports r SET area_id = (
            SELECT a.id FROM areas a WHERE ST_Contains(a.geom, r.geom) ORDER BY ST_Area(a.geom) ASC LIMIT 1
        )
        """
    )
    op.create_index("ix_reports_area_id", "reports", ["area_id"])


def downgrade() -> None:
    op.drop_index("ix_reports_area_id", table_name="reports")
    op.drop_column("reports", "reopen_count")
    op.drop_constraint("fk_reports_area_id", "reports", type_="foreignkey")
    op.drop_column("reports", "area_id")
