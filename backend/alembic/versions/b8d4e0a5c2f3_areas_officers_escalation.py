"""areas, officers and report assignment/escalation columns

Revision ID: b8d4e0a5c2f3
Revises: a7c3d9e4f1b2
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql


revision: str = "b8d4e0a5c2f3"
down_revision: Union[str, Sequence[str], None] = "a7c3d9e4f1b2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column(
            "geom",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_areas_geom", "areas", ["geom"], postgresql_using="gist")

    op.create_table(
        "officers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("telegram_chat_id", sa.String(length=64), nullable=False),
        sa.Column("area_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["area_id"], ["areas.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_officers_area", "officers", ["area_id"])
    op.create_index(
        "uq_one_active_admin",
        "officers",
        ["role"],
        unique=True,
        postgresql_where=sa.text("role = 'admin' AND active"),
    )

    op.add_column(
        "reports",
        sa.Column("assigned_officer_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("reports", sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("reports", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_reports_assigned_officer",
        "reports",
        "officers",
        ["assigned_officer_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # The escalation job only ever looks at open, unacknowledged, not-yet-escalated
    # reports, so index exactly those rows (stays tiny however large the table grows).
    op.create_index(
        "ix_reports_pending_escalation",
        "reports",
        ["assigned_at"],
        postgresql_where=sa.text(
            "status = 'OPEN' AND acknowledged_at IS NULL AND escalated_at IS NULL "
            "AND assigned_officer_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_reports_pending_escalation", table_name="reports")
    op.drop_constraint("fk_reports_assigned_officer", "reports", type_="foreignkey")
    op.drop_column("reports", "escalated_at")
    op.drop_column("reports", "acknowledged_at")
    op.drop_column("reports", "assigned_at")
    op.drop_column("reports", "assigned_officer_id")
    op.drop_index("uq_one_active_admin", table_name="officers")
    op.drop_index("ix_officers_area", table_name="officers")
    op.drop_table("officers")
    op.drop_index("idx_areas_geom", table_name="areas")
    op.drop_table("areas")
