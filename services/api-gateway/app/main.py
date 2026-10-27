"""NIS API Gateway（8000）。

浏览器唯一入口：路由、``X-Request-ID`` 贯穿、统一错误体与 Workflow Coordinator。
Gateway 不拥有 Schema，也不作为唯一授权点（docs/architecture.md 第 5、10 节）。

Issue #7 只装配健康检查与就绪探针；业务路由在 #8 起按契约接入。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.config import load_settings

from app.readiness import probe_downstreams

settings = load_settings("api-gateway")

app = create_service_app(
    settings,
    database=None,
    readiness_probe=lambda: probe_downstreams(settings.downstream),
)
