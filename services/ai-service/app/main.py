"""AI Assistance Service（8006）。

四环节统一建议与人工确认，Schema ``nis_ai``（可降级）。不接外部模型，
按环节生成可复现的规则模板；``AI_ENABLED=false`` 时按契约返回 503，人工流程继续。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_ai 表
from app.routers import router as ai_router

settings = load_settings("ai-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[ai_router])
wire_clients(app, settings, with_iam=True)
