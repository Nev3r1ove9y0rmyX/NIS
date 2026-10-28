"""Analysis Service（8003）。

分析报告、侦察引用与决策员指派，Schema ``nis_analysis``。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_analysis 表
from app.routers import router as analysis_router

settings = load_settings("analysis-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[analysis_router])
wire_clients(app, settings, with_iam=True, with_recon=True)
