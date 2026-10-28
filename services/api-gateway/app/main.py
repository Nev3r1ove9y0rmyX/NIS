"""NIS API Gateway（8000）。

浏览器唯一入口：认证入口、路由转发、``X-Request-ID`` 贯穿、统一错误体、Workflow Coordinator。
Gateway 不拥有 Schema，也不作为唯一授权点（docs/architecture.md 第 5、10 节）。
"""

from __future__ import annotations

from nis_shared.app import create_service_app
from nis_shared.clients import InternalClient
from nis_shared.config import load_settings
from nis_shared.wiring import wire_clients

from app.readiness import probe_downstreams
from app.routes_admin import router as admin_router
from app.routes_auth import router as auth_router

settings = load_settings("api-gateway")

app = create_service_app(
    settings,
    database=None,
    routers=[auth_router, admin_router],
    readiness_probe=lambda: probe_downstreams(settings.downstream),
)
wire_clients(app, settings, with_iam=True)
app.state.iam_http = InternalClient(
    settings.downstream["iam-service"], service_name="api-gateway"
)
