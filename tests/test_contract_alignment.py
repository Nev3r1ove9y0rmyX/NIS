"""契约一致性测试（B 的 P1 任务，tests/README.md「contract」层）。

三条断言：

1. **不许发明路由**：实现的每个路径都必须能在冻结的 OpenAPI 契约里找到；
2. **不许静默漏实现**：契约里有的路径，要么已实现，要么在 ``KNOWN_PENDING`` 里登记原因；
3. **错误体与健康检查符合契约**：错误响应必须是 ``{code, message, request_id}``，健康检查必须符合 ``Health``。

任何一处不一致都会让测试失败，避免「契约写一套、代码写一套」。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from conftest import ROOT, import_service

OPENAPI_DIR = ROOT / "contracts" / "openapi"

#: 服务名 → 契约文件
CONTRACTS = {
    "api-gateway": "api-gateway.yaml",
    "iam-service": "iam-service.yaml",
    "recon-service": "recon-service.yaml",
    "analysis-service": "analysis-service.yaml",
    "decision-service": "decision-service.yaml",
    "execution-service": "execution-service.yaml",
    "ai-service": "ai-service.yaml",
    "audit-service": "audit-service.yaml",
}

#: 实现了但契约里还没有的路由：必须有跟进 Issue，修完后从清单删除。
KNOWN_EXTRA: set[tuple[str, str, str]] = {
    # Gateway 契约有 revokeUserRole，但 iam-service.yaml 缺内部路由；等 A 补（Issue #26）
    ("iam-service", "DELETE", "/internal/v1/users/{user_id}/roles/{role_code}"),
}

#: 契约里有但本期未实现的路由：必须写清原因，防止「忘了」。
KNOWN_PENDING: set[tuple[str, str, str]] = {
    # 证据下载依赖受控目录与备份方案（决策 D-02），由 D 的存储方案落地后补
    ("api-gateway", "GET", "/recon-records/{record_id}/evidence/{evidence_id}"),
    ("api-gateway", "GET", "/assignments/{assignment_id}/evidence/{evidence_id}"),
}

HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

#: 契约用 servers 里的 url 声明前缀（公共契约是 /api/v1），实现里写在路由上，比对时去掉
CONTRACT_PREFIX = {"api-gateway": "/api/v1"}


def _normalize(service: str, path: str) -> str:
    prefix = CONTRACT_PREFIX.get(service)
    if prefix and path.startswith(prefix + "/"):
        return path[len(prefix) :]
    if prefix and path == prefix:
        return "/"
    return path


def _contract_routes(filename: str) -> set[tuple[str, str]]:
    document = yaml.safe_load((OPENAPI_DIR / filename).read_text(encoding="utf-8"))
    routes: set[tuple[str, str]] = set()
    for path, operations in document["paths"].items():
        for method in operations:
            if method.lower() in HTTP_METHODS:
                routes.add((method.upper(), path))
    return routes


def _app_routes(service: str) -> set[tuple[str, str]]:
    """用应用自身生成的 OpenAPI 取实际暴露的路径。

    FastAPI 新版本把 include_router 包成 ``_IncludedRouter``，直接遍历 ``app.routes``
    拿不到子路由的 path/methods，因此统一以 ``app.openapi()`` 为准。
    """

    _, main = import_service(service)
    schema = main.app.openapi()
    routes: set[tuple[str, str]] = set()
    for path, operations in schema.get("paths", {}).items():
        for method in operations:
            if method.lower() in HTTP_METHODS:
                routes.add((method.upper(), _normalize(service, path)))
    return routes


@pytest.mark.parametrize("service", sorted(CONTRACTS))
def test_no_invented_routes(service: str) -> None:
    """实现的路由必须在契约里，否则先改契约（破坏性变更要走评审）。"""

    contract = _contract_routes(CONTRACTS[service])
    implemented = _app_routes(service)
    extra = {
        (method, path)
        for method, path in implemented - contract
        if (service, method, path) not in KNOWN_EXTRA
    }
    assert not extra, f"{service} 有契约未登记的路由：{sorted(extra)}"


@pytest.mark.parametrize("service", sorted(CONTRACTS))
def test_no_silently_missing_routes(service: str) -> None:
    """契约里的路由要么实现，要么在 KNOWN_PENDING 里写明原因。"""

    contract = _contract_routes(CONTRACTS[service])
    implemented = _app_routes(service)
    missing = {
        (method, path)
        for method, path in contract - implemented
        if (service, method, path) not in KNOWN_PENDING
    }
    assert not missing, f"{service} 还有契约内的接口没实现：{sorted(missing)}"


def test_known_pending_are_still_pending() -> None:
    """登记为「未实现」的接口一旦实现，必须从清单删除，避免清单腐化。"""

    resolved = set()
    for service, method, path in KNOWN_PENDING:
        if (method, path) in _app_routes(service):
            resolved.add((service, method, path))
    assert not resolved, f"这些接口已经实现，请从 KNOWN_PENDING 删除：{sorted(resolved)}"


def test_known_extra_are_still_extra() -> None:
    """临时多出来的路由一旦进了契约，也要从清单删除。"""

    stale = set()
    for service, method, path in KNOWN_EXTRA:
        if (method, path) in _contract_routes(CONTRACTS[service]):
            stale.add((service, method, path))
    assert not stale, f"这些路由已进契约，请从 KNOWN_EXTRA 删除：{sorted(stale)}"


def test_error_body_matches_contract_schema() -> None:
    """错误体必备字段与 common.yaml 的 Error 一致。"""

    from fastapi.testclient import TestClient

    _, main = import_service("api-gateway")
    client = TestClient(main.app)
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401
    body = response.json()
    assert {"code", "message", "request_id"} <= set(body)
    assert isinstance(body["code"], str) and body["code"].isupper()
    assert response.headers.get("X-Request-ID") == body["request_id"]


def test_health_matches_contract_schema() -> None:
    """健康检查必须回 status/service/checked_at（common.yaml Health）。"""

    from fastapi.testclient import TestClient

    for service in CONTRACTS:
        _, main = import_service(service)
        client = TestClient(main.app)
        body = client.get("/health/live").json()
        assert {"status", "service", "checked_at"} <= set(body)
        assert body["service"] == service
