"""Audit Service（8007）。

只追加的审计事件与调用链，Schema ``nis_audit``。业务账号对该 Schema 只有 SELECT/INSERT
（``audit_trace_index`` 是派生索引，允许 UPDATE 以累加计数）。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_audit 表
from app.routers import router as audit_router

settings = load_settings("audit-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database, routers=[audit_router])
# 查询与调用链要校验 audit:read，因此审计服务也需要 IAM 客户端做本地验签。
# 审计服务不写自己的审计（避免自引用），故 with_audit=False。
wire_clients(app, settings, with_iam=True, with_audit=False)
