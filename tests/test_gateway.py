"""Gateway 用例（Issue #8）：入口鉴权、转发、角色上下文与管理权限。

内部调用用 ASGI 桥接，真实走 IAM 的路由与数据库，不 mock 业务判断。
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service
from test_auth import ADMIN_PASSWORD, DEMO_PASSWORD, AsgiBridge

API = "/api/v1"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def write(self, **kwargs) -> bool:  # noqa: ANN003
        self.events.append(kwargs)
        return True


@pytest.fixture
def stack():
    """装配 IAM + Gateway：Gateway 通过 ASGI 桥接调用真实 IAM。"""

    from nis_shared.clients import IamClient, InternalClient
    from nis_shared.db import Database

    import_service("iam-service")
    database = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(database)

    seed_module = importlib.import_module("app.seed")
    seed_module.seed(database, admin_password=ADMIN_PASSWORD, demo_password=DEMO_PASSWORD)

    iam_main = importlib.import_module("app.main")
    iam_app = iam_main.app
    iam_app.state.database = database
    iam_audit = RecordingAudit()
    iam_app.state.audit = iam_audit

    gateway_main = import_service("api-gateway")[1]
    gateway_app = gateway_main.app
    transport = AsgiBridge(iam_app)
    gateway_app.state.iam = IamClient("http://iam-service:8001", transport=transport)
    gateway_app.state.iam_http = InternalClient("http://iam-service:8001", transport=transport)
    gateway_audit = RecordingAudit()
    gateway_app.state.audit = gateway_audit

    iam_models = import_service("iam-service")[0]
    return TestClient(gateway_app), TestClient(iam_app), database, gateway_audit, iam_models


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()


def _headers(token: str, role_context: str | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if role_context:
        headers["X-Role-Context"] = role_context
    return headers


def test_login_through_gateway_returns_current_user(stack) -> None:
    client, _, _, _, _ = stack
    body = _login(client, "recon01", DEMO_PASSWORD)
    assert set(body) == {"access_token", "refresh_token", "token_type", "expires_in", "user"}
    user = body["user"]
    assert user["username"] == "recon01"
    assert user["roles"] == ["reconnaissance"]
    assert user["organization"]["code"] == "ORG-REC"
    assert "recon:submit" in user["permissions"]


def test_login_failure_uses_contract_error_body(stack) -> None:
    client, _, _, _, _ = stack
    response = client.post(f"{API}/auth/login", json={"username": "recon01", "password": "not-the-password"})
    assert response.status_code == 401
    body = response.json()
    assert body["code"] == "UNAUTHENTICATED"
    assert body["request_id"]
    assert "password" not in body["message"].lower()


def test_login_validation_is_422(stack) -> None:
    client, _, _, _, _ = stack
    response = client.post(f"{API}/auth/login", json={"username": "recon01", "password": "short"})
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_protected_endpoints_require_token(stack) -> None:
    client, _, _, _, _ = stack
    for path in (f"{API}/auth/me", f"{API}/admin/users", f"{API}/candidates?target_role=analyst"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["code"] == "UNAUTHENTICATED"


def test_me_and_organizations_through_gateway(stack) -> None:
    client, _, _, _, _ = stack
    token = _login(client, "analyst01", DEMO_PASSWORD)["access_token"]

    me = client.get(f"{API}/auth/me", headers=_headers(token))
    assert me.status_code == 200
    assert me.json()["username"] == "analyst01"

    orgs = client.get(f"{API}/organizations", headers=_headers(token))
    assert orgs.status_code == 200
    codes = {item["code"] for item in orgs.json()["items"]}
    assert {"ORG-CMD", "ORG-REC", "ORG-ANA", "ORG-DEC", "ORG-EXE"} <= codes


def test_candidates_require_target_role(stack) -> None:
    client, _, _, _, _ = stack
    token = _login(client, "recon01", DEMO_PASSWORD)["access_token"]
    ok = client.get(f"{API}/candidates", headers=_headers(token), params={"target_role": "analyst"})
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["total"] == 2
    assert payload["items"][0]["organization"]["code"] == "ORG-ANA"

    missing = client.get(f"{API}/candidates", headers=_headers(token))
    assert missing.status_code == 422


def test_admin_endpoints_reject_business_role_and_audit(stack) -> None:
    client, _, _, audit, _ = stack
    token = _login(client, "recon01", DEMO_PASSWORD)["access_token"]
    response = client.get(f"{API}/admin/users", headers=_headers(token))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    denied = [e for e in audit.events if e["action"] == "gateway.permission.denied"]
    assert denied and denied[-1]["details"]["permission"] == "iam:manage"


def test_admin_can_manage_users_through_gateway(stack) -> None:
    client, _, database, _, iam_models = stack
    admin = _login(client, "admin", ADMIN_PASSWORD)["access_token"]
    headers = _headers(admin, "administrator")

    listing = client.get(f"{API}/admin/users", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 8

    from sqlalchemy import select

    

    with database.session() as db:
        org_id = db.scalars(select(iam_models.OrganizationUnit).where(iam_models.OrganizationUnit.code == "ORG-EXE")).one().id

    created = client.post(
        f"{API}/admin/users",
        headers=headers,
        json={
            "username": "exec03",
            "password": "another-pass-2026",
            "display_name": "执行员丙",
            "organization_id": org_id,
            "role_codes": ["executor"],
        },
    )
    assert created.status_code == 201, created.text
    new_id = created.json()["id"]
    assert created.json()["organization"]["code"] == "ORG-EXE"

    roles = client.get(f"{API}/admin/users/{new_id}/roles", headers=headers)
    assert roles.status_code == 200
    assert roles.json()["items"][0]["role_code"] == "executor"

    revoked = client.delete(f"{API}/admin/users/{new_id}/roles/executor", headers=headers)
    assert revoked.status_code == 204

    after = client.get(f"{API}/admin/users/{new_id}/roles", headers=headers)
    assert after.json()["items"] == []


def test_multi_role_admin_without_role_context_is_rejected(stack) -> None:
    client, _, _, _, _ = stack
    admin = _login(client, "admin", ADMIN_PASSWORD)["access_token"]
    response = client.get(f"{API}/admin/users", headers=_headers(admin))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_new_user_can_login_immediately(stack) -> None:
    client, _, database, _, iam_models = stack
    admin = _login(client, "admin", ADMIN_PASSWORD)["access_token"]
    headers = _headers(admin, "administrator")

    from sqlalchemy import select

    

    with database.session() as db:
        org_id = db.scalars(select(iam_models.OrganizationUnit).where(iam_models.OrganizationUnit.code == "ORG-REC")).one().id

    client.post(
        f"{API}/admin/users",
        headers=headers,
        json={
            "username": "recon09",
            "password": "brand-new-pass",
            "display_name": "侦察员壬",
            "organization_id": org_id,
            "role_codes": ["reconnaissance"],
        },
    )
    login = client.post(f"{API}/auth/login", json={"username": "recon09", "password": "brand-new-pass"})
    assert login.status_code == 200
    assert login.json()["user"]["roles"] == ["reconnaissance"]


def test_logout_is_audited_and_returns_204(stack) -> None:
    client, _, _, audit, _ = stack
    token = _login(client, "dmaker01", DEMO_PASSWORD)["access_token"]
    response = client.post(f"{API}/auth/logout", headers=_headers(token))
    assert response.status_code == 204
    assert any(event["action"] == "auth.logout" for event in audit.events)


def test_refresh_through_gateway(stack) -> None:
    client, _, _, _, _ = stack
    tokens = _login(client, "exec01", DEMO_PASSWORD)
    refreshed = client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"]
