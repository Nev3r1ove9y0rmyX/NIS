"""健康检查与统一错误体（Issue #7 验收：每个服务就绪检查能反映数据库状态）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service

PERSISTENT_SERVICES = [
    "iam-service",
    "recon-service",
    "analysis-service",
    "decision-service",
    "execution-service",
    "ai-service",
    "audit-service",
]
ALL_SERVICES = ["api-gateway", *PERSISTENT_SERVICES]


@pytest.mark.parametrize("service", ALL_SERVICES)
def test_live_reports_service_identity(service: str) -> None:
    _, main = import_service(service)
    client = TestClient(main.app)
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == service
    # 契约要求 checked_at 为 ISO 8601 UTC（common.yaml#Timestamp）
    assert body["checked_at"].endswith("Z")
    assert response.headers["X-Request-ID"]


@pytest.mark.parametrize("service", PERSISTENT_SERVICES)
def test_ready_ok_with_database(service: str, sqlite_database) -> None:
    import_service(service)
    ensure_schema(sqlite_database)

    from nis_shared.app import create_service_app
    from nis_shared.config import ServiceSettings

    app = create_service_app(ServiceSettings(service=service), database=sqlite_database)
    client = TestClient(app)
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["dependencies"]["database"] == "ok"


@pytest.mark.parametrize("service", PERSISTENT_SERVICES)
def test_ready_503_when_database_down(service: str, monkeypatch) -> None:
    from nis_shared.app import create_service_app
    from nis_shared.config import ServiceSettings
    from nis_shared.db import Database

    database = Database("sqlite+pysqlite:///:memory:")
    monkeypatch.setattr(database, "ping", lambda: False)
    app = create_service_app(ServiceSettings(service=service), database=database)
    client = TestClient(app)

    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    # 503 走统一错误体（契约 ServiceUnavailable → Error）
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert body["request_id"]
    assert body["details"]["dependencies"]["database"] == "down"


def test_error_body_matches_contract() -> None:
    from fastapi import APIRouter
    from nis_shared.app import create_service_app
    from nis_shared.config import ServiceSettings
    from nis_shared.errors import ApiError

    router = APIRouter()

    @router.get("/_test/forbidden")
    def _forbidden() -> None:
        raise ApiError("FORBIDDEN", "没有执行该操作的权限", details={"permission": "recon:submit"})

    @router.get("/_test/boom")
    def _boom() -> None:
        raise RuntimeError("内部实现细节不应外泄")

    app = create_service_app(ServiceSettings(service="iam-service"), routers=[router])
    client = TestClient(app, raise_server_exceptions=False)

    trace_id = "11111111-1111-4111-8111-111111111111"
    forbidden = client.get("/_test/forbidden", headers={"X-Request-ID": trace_id})
    assert forbidden.status_code == 403
    body = forbidden.json()
    assert set(body) >= {"code", "message", "request_id", "details"}
    # 传入的追踪 ID 必须原样透传，便于审计还原
    assert body["request_id"] == trace_id

    boom = client.get("/_test/boom")
    assert boom.status_code == 500
    assert boom.json()["code"] == "INTERNAL_ERROR"
    assert "内部实现细节" not in boom.text
    assert "RuntimeError" not in boom.text


def test_validation_error_is_422() -> None:
    from fastapi import APIRouter, Query
    from nis_shared.app import create_service_app
    from nis_shared.config import ServiceSettings

    router = APIRouter()

    @router.get("/_test/page")
    def _page(page_size: int = Query(20, ge=1, le=100)) -> dict[str, int]:
        return {"page_size": page_size}

    app = create_service_app(ServiceSettings(service="iam-service"), routers=[router])
    client = TestClient(app)

    response = client.get("/_test/page", params={"page_size": 500})
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["details"]["issues"][0]["field"] == "page_size"


def test_gateway_ready_reports_downstream_state(monkeypatch) -> None:
    main = import_service("api-gateway")[1]

    import httpx

    class _Response:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    def fake_get(url: str, timeout: float):  # noqa: ARG001
        # 默认下游地址形如 http://127.0.0.1:8001；只让 IAM（8001）可达
        if ":8001" in url:
            return _Response(200)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", fake_get)
    client = TestClient(main.app)
    response = client.get("/health/ready")
    # 只有 iam 可达，其余不可达 → 未就绪
    assert response.status_code == 503
    dependencies = response.json()["details"]["dependencies"]
    assert dependencies["iam-service"] == "ok"
    assert dependencies["recon-service"] == "unreachable"
