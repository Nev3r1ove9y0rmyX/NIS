"""SQLAlchemy 基类与通用列。

对应 ``docs/data-model.md`` 第 1.2、1.3 节：

- 主键统一 ``id``（UUID 字符串 ``CHAR(36)``），不为接口暴露自增主键；
- 业务表带 ``version`` 乐观锁与 ``created_at/created_by/updated_at/updated_by``；
- 只追加表（证据、审计）不设 ``version``/``updated_*``；
- 时间列 ``DATETIME(3)``，服务端统一写 UTC。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, DateTime, Integer, String
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.orm import declarative_base

Base = declarative_base()

#: ``DATETIME(3)``：MySQL 用毫秒精度，SQLite 用普通 DATETIME（测试环境）。
DateTime3 = DateTime().with_variant(mysql.DATETIME(fsp=3), "mysql")
#: ``INT UNSIGNED``
UInt = Integer().with_variant(mysql.INTEGER(unsigned=True), "mysql")
#: ``BIGINT UNSIGNED``；SQLite 的自增主键必须是 INTEGER 才能当 rowid 别名
UBigInt = (
    BigInteger()
    .with_variant(mysql.BIGINT(unsigned=True), "mysql")
    .with_variant(sqlite.INTEGER(), "sqlite")
)


def utcnow() -> datetime:
    """返回 UTC 的 naive 时间，用于 ``DATETIME(3)`` 列。"""

    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_uuid() -> str:
    return str(uuid.uuid4())


def uuid_pk() -> Column:
    return Column(String(36), primary_key=True, default=new_uuid)


class HeadFieldsMixin:
    """业务表标准列（数据模型 1.3）。"""

    version = Column(Integer, nullable=False, default=1, server_default="1")
    created_at = Column(DateTime3, nullable=False, default=utcnow)
    created_by = Column(String(36), nullable=False)
    updated_at = Column(DateTime3, nullable=False, default=utcnow, onupdate=utcnow)
    updated_by = Column(String(36), nullable=False)
