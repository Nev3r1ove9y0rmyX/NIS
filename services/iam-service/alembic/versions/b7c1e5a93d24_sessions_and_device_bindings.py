"""新增会话与设备绑定表

Revision ID: b7c1e5a93d24
Revises: 50de44a298b7
Create Date: 2026-11-03 02:30:00

本地联调时在线状态（user_sessions）与账号设备绑定（user_device_bindings）是后加的功能，
此前未生成迁移，导致容器部署后登录 500。本迁移补齐这两张表。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import mysql

revision: str = "b7c1e5a93d24"
down_revision: str | None = "50de44a298b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DATETIME3 = sa.DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")


def upgrade() -> None:
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("last_seen_at", DATETIME3, nullable=True),
        sa.Column("last_ip", sa.String(length=64), nullable=True),
        sa.Column("revoked_at", DATETIME3, nullable=True),
        sa.Column("revoked_by", sa.String(length=36), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", DATETIME3, nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("updated_at", DATETIME3, nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"], unique=False)

    op.create_table(
        "user_device_bindings",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("allowed_ips", sa.Text(), nullable=False),
        sa.Column("allowed_macs", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_at", DATETIME3, nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("updated_at", DATETIME3, nullable=False),
        sa.Column("updated_by", sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_user_device_bindings_user_id"),
    )


def downgrade() -> None:
    op.drop_table("user_device_bindings")
    op.drop_index("ix_user_sessions_user_id", table_name="user_sessions")
    op.drop_table("user_sessions")
