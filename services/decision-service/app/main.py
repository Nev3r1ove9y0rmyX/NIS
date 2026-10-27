"""Decision Service（8004）。

指令、冲突检查与总体状态重算，Schema ``nis_decision``。
``commands.status`` 只在本服务重算（决策 D-01）。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_decision 表
from app.routers import router as decision_router

settings = load_settings("decision-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[decision_router])
# 下达指令要读分析报告（授权接口）、创建执行分配（Execution）、校验执行员（IAM）
wire_clients(app, settings, with_iam=True, with_analysis=True, with_execution=True)
