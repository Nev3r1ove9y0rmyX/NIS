"""IAM & Organization Service（8001）。

登录、用户/角色/权限/组织与候选接收人，Schema ``nis_iam``。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database

from app import models  # noqa: F401  导入即注册 nis_iam 表，供迁移与测试使用

settings = load_settings("iam-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database)
