"""account recovery: one-time email links, verified addresses, sign-in tokens that die on reset

Revision ID: a1d7e3f9b5c2
Revises: f9c5d1e7a3b6
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a1d7e3f9b5c2"
down_revision: Union[str, Sequence[str], None] = "f9c5d1e7a3b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True))
    # Staff accounts are made by the main administrator, who vouches for the address. Citizens verify theirs.
    op.execute("UPDATE users SET email_verified_at = now() WHERE role IN ('officer', 'admin')")

    op.create_table(
        "auth_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_auth_tokens_user", "auth_tokens", ["user_id", "kind"])


def downgrade() -> None:
    op.drop_index("ix_auth_tokens_user", table_name="auth_tokens")
    op.drop_table("auth_tokens")
    op.drop_column("users", "password_changed_at")
    op.drop_column("users", "email_verified_at")
