"""add postgis geom

Revision ID: e1e34496a6ba
Revises: 153d96b82a1c
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry


revision: str = "e1e34496a6ba"
down_revision: Union[str, Sequence[str], None] = "153d96b82a1c"
branch_labels = None
depends_on = None

def upgrade() -> None:

    op.add_column(
        "reports",
        sa.Column(
            "geom",
            Geometry(
                geometry_type="POINT",
                srid=4326,
                spatial_index=False,
            ),
            nullable=True,
        ),
    )

    op.execute("""
        UPDATE reports
        SET geom = ST_SetSRID(
            ST_MakePoint(longitude, latitude),
            4326
        )
    """)

    op.create_index(
        "idx_reports_geom",
        "reports",
        ["geom"],
        unique=False,
        postgresql_using="gist",
    )

    op.alter_column(
        "reports",
        "geom",
        nullable=False,
    )

def downgrade() -> None:

    op.drop_column(
        "reports",
        "geom",
    )