"""baseline schema

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-07-04

This is the BASELINE migration: it creates every table exactly as defined
in models.py at the time Alembic was introduced to this project, including
the requirement #3/#4/#5 columns (isolation_status/recalled_at on
asset_exceptions, is_deleted/deleted_at on users, quantity_returned on
asset_checkouts).

WHY A HANDWRITTEN BASELINE INSTEAD OF AUTOGENERATE?
This project previously created tables via `Base.metadata.create_all()` in
database.py -> init_db() (still present, and harmless to leave running --
see README.md's Alembic section for the recommended handoff). Since there
was no prior migration history to diff against, this file is written by
hand to exactly mirror models.py, giving you a clean starting point. Every
schema change from here on should be a NEW migration generated with
`alembic revision --autogenerate -m "description"`.
"""
from alembic import op
import sqlalchemy as sa

# Alembic identifiers, used by Alembic itself -- do not edit by hand.
revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "asset_types",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(), nullable=False, unique=True),
        sa.Column("total_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("available_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("email", sa.String(), nullable=False, unique=True, index=True),
        sa.Column("role", sa.String(), server_default="staff"),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("department", sa.String(), nullable=True),
        sa.Column("department_role", sa.String(), nullable=True),
    )

    op.create_table(
        "outsiders",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contact_details", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=True),
    )

    op.create_table(
        "asset_exceptions",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("asset_type_id", sa.Integer(), sa.ForeignKey("asset_types.id"), nullable=False),
        sa.Column("serial_number", sa.String(), nullable=False, unique=True),
        sa.Column("status_label", sa.String(), nullable=False, server_default="Undeployable"),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("isolation_status", sa.String(), nullable=False, server_default="isolated"),
        sa.Column("recalled_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("operator", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("details", sa.String(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "asset_checkouts",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("asset_id", sa.Integer(), sa.ForeignKey("asset_types.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("outsider_id", sa.Integer(), sa.ForeignKey("outsiders.id"), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("quantity_returned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checkout_date", sa.DateTime(), nullable=True),
        sa.Column("due_date", sa.DateTime(), nullable=True),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(), server_default="active"),
    )


def downgrade() -> None:
    # Drop in reverse dependency order so foreign keys don't block the drop.
    op.drop_table("asset_checkouts")
    op.drop_table("audit_logs")
    op.drop_table("asset_exceptions")
    op.drop_table("outsiders")
    op.drop_table("users")
    op.drop_table("asset_types")
