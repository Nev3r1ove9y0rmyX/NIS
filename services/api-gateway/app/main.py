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
from app.routes_records import router as records_router

settings = load_settings("api-gateway")

app = create_service_app(
    settings,
    database=None,
    routers=[auth_router, admin_router, records_router],
    readiness_probe=lambda: probe_downstreams(settings.downstream),
)
wire_clients(app, settings, with_iam=True)
# Gateway 自身的转发客户端：每个上游一个，错误映射与超时统一由 InternalClient 处理
for _name, _env in (
    ("iam", "iam-service"),
    ("recon", "recon-service"),
    ("analysis", "analysis-service"),
    ("decision", "decision-service"),
    ("execution", "execution-service"),
    ("ai", "ai-service"),
):
    setattr(
        app.state,
        f"{_name}_http",
        InternalClient(settings.downstream[_env], service_name="api-gateway"),
    )
