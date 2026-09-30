"""Schema iniziale: applications, deployments.

Revision ID: 0001
Revises:
Create Date: 2026-09-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "applications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("repository", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "deployments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "application_id", sa.Integer(), sa.ForeignKey("applications.id"), nullable=False
        ),
        sa.Column("environment", sa.String(length=32), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column("commit", sa.String(length=64), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("result", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_deployments_app_env_time",
        "deployments",
        ["application_id", "environment", "deployed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_deployments_app_env_time", table_name="deployments")
    op.drop_table("deployments")
    op.drop_table("applications")
