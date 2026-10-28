"""audit-service 的 Alembic 环境。

连接串来自服务配置（环境变量），仓库里没有口令；迁移顺序由 scripts/migrate_all.py 统一编排
（docs/data-model.md 第 12 节）。
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from nis_shared.config import load_settings
from nis_shared.models import Base

from app import models  # noqa: F401  导入即注册本服务的表

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    """优先用 NIS_ALEMBIC_URL（迁移账号），否则退回服务运行账号。"""

    override = os.environ.get("NIS_ALEMBIC_URL", "").strip()
    if override:
        return override
    url = load_settings("audit-service").db_url
    if not url:
        raise RuntimeError("未配置数据库连接：请设置 NIS_ALEMBIC_URL 或对应 *_DB_* 环境变量")
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), future=True, pool_pre_ping=True)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
