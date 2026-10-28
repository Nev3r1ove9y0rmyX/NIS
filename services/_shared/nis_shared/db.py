"""数据库连接与会话。

每个服务只连自己 Schema 的账号（``docs/data-ownership.md`` 第 2 节）。Gateway 不建库。
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class Database:
    """一个服务的数据源：自带引擎与会话工厂，便于测试替换为 SQLite。"""

    def __init__(self, url: str, *, echo: bool = False, pool_size: int = 5) -> None:
        if not url:
            raise ValueError("数据库 URL 为空：请检查服务配置或 <PREFIX>_DB_URL")
        self.url = url
        if url.startswith("sqlite"):
            # 内存库必须共用同一个连接，否则每个连接（含 TestClient 的线程）都会看到空库
            from sqlalchemy.pool import StaticPool  # noqa: PLC0415

            pool_kwargs = (
                {"poolclass": StaticPool} if ":memory:" in url else {}
            )
            self.engine: Engine = create_engine(
                url,
                future=True,
                connect_args={"check_same_thread": False},
                **pool_kwargs,
            )
        else:
            self.engine = create_engine(
                url,
                future=True,
                echo=echo,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=pool_size,
                max_overflow=pool_size,
            )
        self.session_factory = sessionmaker(
            bind=self.engine, expire_on_commit=False, future=True
        )

    @contextlib.contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def ping(self) -> bool:
        """就绪检查用；不抛异常，失败返回 False。"""

        try:
            with self.engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    def create_all(self) -> None:
        """只在测试与本地初始化使用；正式环境走 Alembic 迁移。"""

        Base.metadata.create_all(self.engine)
