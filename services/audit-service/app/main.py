"""Audit Service（8007）。

只追加的审计事件与调用链，Schema ``nis_audit``。业务账号对该 Schema 只有 SELECT/INSERT。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database

from app import models  # noqa: F401  导入即注册 nis_audit 表
from app.routers import router as audit_router

settings = load_settings("audit-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[audit_router])
