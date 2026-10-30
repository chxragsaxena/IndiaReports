"""before/after fix verification: photo kind and the verdict

Revision ID: d7a3b9c5e1f4
Revises: c6f2a8b4d0e3
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "d7a3b9c5e1f4"
down_revision: Union[str, Sequence[str], None] = "c6f2a8b4d0e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("report_images", sa.Column("kind", sa.String(10), nullable=False, server_default="report"))
    op.add_column("report_images", sa.Column("verification", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("report_images", "verification")
    op.drop_column("report_images", "kind")
