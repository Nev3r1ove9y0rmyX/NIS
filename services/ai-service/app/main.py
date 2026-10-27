from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings
from nis_shared.db import Database

from app import models  # noqa: F401  导入即注册本服务表

settings = load_settings("ai-service")
database = Database(settings.db_url)

app = create_service_app(settings, database=database)
