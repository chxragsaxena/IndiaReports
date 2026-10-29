"""report_cells: precomputed grid rollup for clusters and dashboard counts

Revision ID: c9e5f1b6d3a4
Revises: b8d4e0a5c2f3

Clusters and dashboard numbers used to aggregate the whole reports table on every
cache miss (cost grows with the table). They now read this rollup, whose size depends
on the map grid, not on the number of reports. The application keeps it current in
the same transaction as every report change.

NOTE for very large existing tables: the backfill below is one statement per level.
For hundreds of millions of rows run it in chunks (or `python -m scripts.rebuild_cells`
during a quiet period) instead of through this migration.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9e5f1b6d3a4"
down_revision: Union[str, Sequence[str], None] = "b8d4e0a5c2f3"
branch_labels = None
depends_on = None

# Keep in sync with app/services/cell_service.py::LEVELS.
LEVELS = {3: 2.0, 4: 1.2, 5: 0.7, 6: 0.35, 7: 0.18, 8: 0.1, 9: 0.05, 10: 0.025}


def upgrade() -> None:
    op.create_table(
        "report_cells",
        sa.Column("level", sa.SmallInteger(), nullable=False),
        sa.Column("cx", sa.Integer(), nullable=False),
        sa.Column("cy", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("category", sa.String(length=50), nullable=False),
        sa.Column("cnt", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("sum_lat", sa.Float(), nullable=False, server_default="0"),
        sa.Column("sum_lng", sa.Float(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("level", "cx", "cy", "status", "category"),
    )

    for level, grid in LEVELS.items():
        op.execute(
            f"""
            INSERT INTO report_cells (level, cx, cy, status, category, cnt, sum_lat, sum_lng)
            SELECT {level}, floor(latitude / {grid})::int, floor(longitude / {grid})::int,
                   status, category, count(*), sum(latitude), sum(longitude)
            FROM reports
            GROUP BY 2, 3, status, category
            """
        )


def downgrade() -> None:
    op.drop_table("report_cells")
