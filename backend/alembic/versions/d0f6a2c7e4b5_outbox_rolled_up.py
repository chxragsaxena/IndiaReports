"""outbox.rolled_up_at: the rollup is applied from events, off the request path

Revision ID: d0f6a2c7e4b5
Revises: c9e5f1b6d3a4

Writes used to update the grid rollup inside the request transaction, so every write
in the same area locked the same few rows and writes serialised. Now a request only
inserts the report and its outbox event; a background applier folds events into the
rollup in batches. Existing events are already reflected by the backfill in the
previous migration, so they are marked as applied.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d0f6a2c7e4b5"
down_revision: Union[str, Sequence[str], None] = "c9e5f1b6d3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("outbox_events", sa.Column("rolled_up_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE outbox_events SET rolled_up_at = now()")
    op.create_index(
        "ix_outbox_not_rolled_up",
        "outbox_events",
        ["id"],
        postgresql_where=sa.text("rolled_up_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_outbox_not_rolled_up", table_name="outbox_events")
    op.drop_column("outbox_events", "rolled_up_at")
