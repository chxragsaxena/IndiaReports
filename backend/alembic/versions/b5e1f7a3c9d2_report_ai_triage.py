"""AI triage of the report text (language, translation, urgency, spam)

Revision ID: b5e1f7a3c9d2
Revises: a4d0e6f2b8c1
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "b5e1f7a3c9d2"
down_revision: Union[str, Sequence[str], None] = "a4d0e6f2b8c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("triage", postgresql.JSONB(), nullable=True))
    op.add_column("reports", sa.Column("triaged_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "triaged_at")
    op.drop_column("reports", "triage")
