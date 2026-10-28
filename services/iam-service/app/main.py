"""IAM & Organization Service（8001）。

登录、用户/角色/权限/组织与候选接收人，Schema ``nis_iam``。
唯一持有 JWT 私钥的服务（docs/architecture.md 第 10 节）。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database
from nis_shared.wiring import wire_clients

from app import models  # noqa: F401  导入即注册 nis_iam 表，供迁移与测试使用
from app.routers import admin_router, auth_router

settings = load_settings("iam-service")
database = Database(settings.db_url)

app = create_service_app(
    settings, database=database, routers=[auth_router, admin_router]
)
# IAM 自己用本地验签，不需要回调自身，因此不创建 IamClient。
wire_clients(app, settings, with_iam=False)
