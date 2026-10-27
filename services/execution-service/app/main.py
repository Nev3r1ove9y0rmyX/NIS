"""Execution Service（8005）。

个人执行分配与执行结果，Schema ``nis_execution``。
本服务只维护个人状态，每次流转后回写 decision-service 重算总体状态（决策 D-01）。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_execution 表
from app.routers import router as execution_router

settings = load_settings("execution-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[execution_router])
wire_clients(app, settings, with_iam=True, with_decision=True)
