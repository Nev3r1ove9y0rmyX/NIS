"""Reconnaissance Service（8002）。

侦察草稿、提交、分析员指派与证据元数据，Schema ``nis_recon``。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_recon 表
from app.routers import router as recon_router

settings = load_settings("recon-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[recon_router])
wire_clients(app, settings, with_iam=True)
