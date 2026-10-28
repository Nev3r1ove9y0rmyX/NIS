"""pytest 公共装配。

7 个服务都用 ``app`` 作为包名（services/README.md 的目录约定），同一进程里无法同时导入。
``import_service`` 做两件事：

1. 每个服务只执行一次 ``models.py``——重复执行会在共享 ``Base.metadata`` 里重复定义同名表；
2. 命中缓存时把该服务的 ``app*`` 模块重新放回 ``sys.modules``，让 ``import app.seed`` 这类
   语句始终解析到同一个服务。
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "services"

if str(SERVICES_DIR / "_shared") not in sys.path:
    sys.path.insert(0, str(SERVICES_DIR / "_shared"))

#: 测试期间所有服务的数据源都指向内存 SQLite，绝不触碰真实库或开发者本机配置。
for _prefix in ("IAM", "RECON", "ANALYSIS", "DECISION", "EXECUTION", "AI", "AUDIT"):
    os.environ.setdefault(f"{_prefix}_DB_URL", "sqlite+pysqlite:///:memory:")

#: 服务名 → (models 模块或 None, main 模块, 该服务的 app* 模块快照)
_CACHE: dict[str, tuple[ModuleType | None, ModuleType, dict[str, ModuleType]]] = {}


def _app_modules() -> dict[str, ModuleType]:
    return {
        name: module
        for name, module in sys.modules.items()
        if name == "app" or name.startswith("app.")
    }


def import_service(service: str) -> tuple[ModuleType | None, ModuleType]:
    """导入指定服务的 ``app.models``（可能不存在）与 ``app.main``。"""

    cached = _CACHE.get(service)
    if cached is not None:
        models, main, snapshot = cached
        for name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            del sys.modules[name]
        sys.modules.update(snapshot)
        return models, main

    service_dir = SERVICES_DIR / service
    if not service_dir.is_dir():
        raise FileNotFoundError(f"服务目录不存在：{service_dir}")
    for mod_name in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
        del sys.modules[mod_name]

    app_dir = service_dir / "app"
    sys.path.insert(0, str(service_dir))
    try:
        models = (
            importlib.import_module("app.models") if (app_dir / "models.py").is_file() else None
        )
        main = importlib.import_module("app.main")
        if (app_dir / "seed.py").is_file():
            importlib.import_module("app.seed")
    finally:
        sys.path.remove(str(service_dir))
    _CACHE[service] = (models, main, _app_modules())
    return models, main


def ensure_schema(database) -> None:  # noqa: ANN001 - 避免在 conftest 顶层导入服务代码
    """按当前已导入的服务模型建表（只用于测试）。"""

    from nis_shared.models import Base

    Base.metadata.create_all(database.engine)


@pytest.fixture(scope="session")
def services_root() -> Path:
    return SERVICES_DIR


@pytest.fixture
def sqlite_database():
    """内存 SQLite 数据源；建表由用例在导入模型后调用 ``ensure_schema``。"""

    from nis_shared.db import Database

    database = Database("sqlite+pysqlite:///:memory:")
    yield database
    database.engine.dispose()
