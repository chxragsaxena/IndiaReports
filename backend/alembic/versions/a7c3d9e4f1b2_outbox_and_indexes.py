"""outbox table and query indexes

Revision ID: a7c3d9e4f1b2
Revises: e1e34496a6ba
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a7c3d9e4f1b2"
down_revision: Union[str, Sequence[str], None] = "e1e34496a6ba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outbox_unpublished",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("published_at IS NULL"),
    )

    # Filters used by the map and dashboard queries.
    op.create_index(
        "ix_reports_status_category",
        "reports",
        ["status", "category"],
        if_not_exists=True,
    )
    op.create_index(
        "ix_reports_created_at",
        "reports",
        [sa.text("created_at DESC")],
        if_not_exists=True,
    )
    op.create_index(
        "ix_reports_state_city",
        "reports",
        ["state", "city"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_reports_state_city", table_name="reports")
    op.drop_index("ix_reports_created_at", table_name="reports")
    op.drop_index("ix_reports_status_category", table_name="reports")
    op.drop_index("ix_outbox_unpublished", table_name="outbox_events")
    op.drop_table("outbox_events")
