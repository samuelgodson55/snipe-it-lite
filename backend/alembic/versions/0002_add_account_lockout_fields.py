"""add account lockout fields to users

Revision ID: 0002_add_account_lockout_fields
Revises: 0001_baseline_schema
Create Date: 2026-07-06

SECURITY: adds the two columns services/auth_service.py's login() needs for
per-account brute-force lockout (see models.py's User.failed_login_attempts
/ locked_until docstring for the full rationale) -- a finer-grained
complement to the existing IP-based rate limiter in
middleware/rate_limit.py.
"""
from alembic import op
import sqlalchemy as sa

# Alembic identifiers, used by Alembic itself -- do not edit by hand.
revision = "0002_add_account_lockout_fields"
down_revision = "0001_baseline_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
