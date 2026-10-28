"""认证与 RBAC 用例（Issue #8）。

全部走真实 FastAPI 应用 + 内存 SQLite：登录、令牌、权限并集、越权审计、账号停用。
内部服务之间的调用用 ASGI 桥接（同一进程内真实走路由），不 mock 业务逻辑。
"""

from __future__ import annotations

import importlib

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service

ADMIN_PASSWORD = "admin-pass-2026"
DEMO_PASSWORD = "demo-pass-2026"


class RecordingAudit:
    """记录审计调用，便于断言「越权必须留痕」而不依赖 audit-service 在线。"""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def write(self, **kwargs) -> bool:  # noqa: ANN003
        self.events.append(kwargs)
        return True

    def of(self, action: str) -> list[dict]:
        return [event for event in self.events if event.get("action") == action]


class AsgiBridge(httpx.BaseTransport):
    """把同步 httpx 请求桥接到另一个 FastAPI 应用（进程内真实路由）。"""

    def __init__(self, app) -> None:  # noqa: ANN001
        self._client = TestClient(app)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._client.request(
            request.method,
            str(request.url),
            headers=dict(request.headers),
            content=request.content,
        )
        return httpx.Response(
            response.status_code,
            headers=dict(response.headers),
            content=response.content,
            request=request,
        )


@pytest.fixture
def env():
    """装配 IAM 服务：内存库 + 种子数据 + 记录型审计。"""

    import_service("iam-service")
    from nis_shared.db import Database

    database = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(database)

    seed_module = importlib.import_module("app.seed")
    seed_module.seed(database, admin_password=ADMIN_PASSWORD, demo_password=DEMO_PASSWORD)

    main = importlib.import_module("app.main")
    app = main.app
    app.state.database = database
    audit = RecordingAudit()
    app.state.audit = audit
    return app, database, audit


def _login(client: TestClient, username: str, password: str) -> dict:
    response = client.post(
        "/internal/v1/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _token(client: TestClient, username: str, password: str) -> str:
    return _login(client, username, password)["token"]["access_token"]


def test_login_returns_session_view(env) -> None:
    app, _, audit = env
    client = TestClient(app)
    body = _login(client, "recon01", DEMO_PASSWORD)
    user = body["user"]
    assert user["username"] == "recon01"
    assert user["roles"] == ["reconnaissance"]
    assert "recon:submit" in user["permissions"]
    assert set(body["token"]) == {"access_token", "refresh_token", "token_type", "expires_in"}
    assert body["token"]["token_type"] == "Bearer"
    assert len(audit.of("auth.login")) == 1


def test_login_rejects_wrong_password_with_audit(env) -> None:
    app, _, audit = env
    client = TestClient(app)
    response = client.post(
        "/internal/v1/auth/login", json={"username": "recon01", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    denied = audit.of("auth.login")
    assert denied and denied[-1]["result"] == "denied"


def test_login_locks_account_after_repeated_failures(env) -> None:
    app, _, _ = env
    client = TestClient(app)
    for _ in range(5):
        client.post(
            "/internal/v1/auth/login", json={"username": "exec01", "password": "wrong-password"}
        )
    blocked = client.post(
        "/internal/v1/auth/login", json={"username": "exec01", "password": DEMO_PASSWORD}
    )
    assert blocked.status_code == 423
    assert blocked.json()["code"] == "ACCOUNT_LOCKED"


def test_me_requires_bearer_token(env) -> None:
    app, _, _ = env
    client = TestClient(app)
    assert client.get("/internal/v1/auth/me").status_code == 401
    token = _token(client, "analyst01", DEMO_PASSWORD)
    ok = client.get("/internal/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["user"]["username"] == "analyst01"


def test_refresh_token_is_not_accepted_as_access_token(env) -> None:
    app, _, _ = env
    client = TestClient(app)
    tokens = _login(client, "dmaker01", DEMO_PASSWORD)["token"]
    wrong = client.get(
        "/internal/v1/auth/me", headers={"Authorization": f"Bearer {tokens['refresh_token']}"}
    )
    assert wrong.status_code == 401

    refreshed = client.post("/internal/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    assert refreshed.json()["access_token"] != tokens["access_token"]


def test_multi_role_user_must_send_role_context(env) -> None:
    app, _, audit = env
    client = TestClient(app)
    # admin 同时具备 decision_maker 与 administrator 两个角色
    token = _token(client, "admin", ADMIN_PASSWORD)

    missing = client.get("/internal/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert missing.status_code == 403
    assert missing.json()["code"] == "FORBIDDEN"

    valid = client.get(
        "/internal/v1/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Role-Context": "administrator"},
    )
    assert valid.status_code == 200

    invalid = client.get(
        "/internal/v1/auth/me",
        headers={"Authorization": f"Bearer {token}", "X-Role-Context": "executor"},
    )
    assert invalid.status_code == 403


def test_single_role_user_may_omit_role_context(env) -> None:
    app, _, _ = env
    client = TestClient(app)
    token = _token(client, "recon02", DEMO_PASSWORD)
    assert client.get("/internal/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_disabled_user_cannot_use_existing_token(env) -> None:
    app, database, _ = env
    client = TestClient(app)
    token = _token(client, "exec02", DEMO_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/internal/v1/auth/me", headers=headers).status_code == 200

    from app import service

    with database.session() as db:
        user = service.get_user_by_username(db, "exec02")
        service.update_user(
            db, user, display_name=None, organization_id=None, status="disabled",
            new_password=None, actor_id="test-actor",
        )

    assert client.get("/internal/v1/auth/me", headers=headers).status_code == 401
    relogin = client.post(
        "/internal/v1/auth/login", json={"username": "exec02", "password": DEMO_PASSWORD}
    )
    assert relogin.status_code == 401


def test_admin_endpoint_requires_permission_and_audits_denial(env) -> None:
    app, _, audit = env
    client = TestClient(app)
    token = _token(client, "recon01", DEMO_PASSWORD)
    response = client.get("/internal/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"
    denied = audit.of("auth.permission.denied")
    assert denied and denied[-1]["details"]["permission"] == "iam:manage"


def test_admin_can_list_and_create_users(env) -> None:
    app, database, _ = env
    client = TestClient(app)
    token = _token(client, "admin", ADMIN_PASSWORD)
    headers = {"Authorization": f"Bearer {token}", "X-Role-Context": "administrator"}

    listing = client.get("/internal/v1/users", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] == 8

    from sqlalchemy import select

    from app.models import OrganizationUnit

    with database.session() as db:
        org_id = db.scalars(select(OrganizationUnit).where(OrganizationUnit.code == "ORG-ANA")).one().id

    created = client.post(
        "/internal/v1/users",
        headers=headers,
        json={
            "username": "analyst03",
            "password": "another-pass-2026",
            "display_name": "分析员丙",
            "organization_id": org_id,
            "role_codes": ["analyst"],
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["roles"] == ["analyst"]

    duplicate = client.post(
        "/internal/v1/users",
        headers=headers,
        json={
            "username": "analyst03",
            "password": "another-pass-2026",
            "display_name": "分析员丙",
            "organization_id": org_id,
            "role_codes": ["analyst"],
        },
    )
    assert duplicate.status_code == 409


def test_permission_change_takes_effect_on_next_request(env) -> None:
    """角色权限被修改后，用户后续请求按新权限生效（Issue #8 验收）。

    所有服务都从 IAM 的 ``/auth/me`` 取权限并集，所以这里直接验证该接口的返回值变化：
    同一个访问令牌，改权限前没有 ``audit:read``，改完后立刻有。
    """

    app, database, _ = env
    client = TestClient(app)

    from sqlalchemy import select

    from app.models import Role

    with database.session() as db:
        role_id = db.scalars(select(Role).where(Role.code == "analyst")).one().id

    analyst_token = _token(client, "analyst01", DEMO_PASSWORD)
    analyst_headers = {"Authorization": f"Bearer {analyst_token}"}
    admin_token = _token(client, "admin", ADMIN_PASSWORD)
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Role-Context": "administrator"}

    before = client.get("/internal/v1/auth/me", headers=analyst_headers)
    assert before.status_code == 200
    assert "audit:read" not in before.json()["user"]["permissions"]

    from app import service

    with database.session() as db:
        role = db.scalars(select(Role).where(Role.id == role_id)).one()
        current = service.role_view(db, role)["permissions"]
    updated = client.put(
        f"/internal/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_codes": sorted(set(current) | {"audit:read"})},
    )
    assert updated.status_code == 200, updated.text
    assert "audit:read" in updated.json()["permissions"]

    after = client.get("/internal/v1/auth/me", headers=analyst_headers)
    assert after.status_code == 200
    assert "audit:read" in after.json()["user"]["permissions"], "权限变更后同一个令牌应立即获得新权限"

    # 恢复原权限后应立刻失去
    restored = client.put(
        f"/internal/v1/roles/{role_id}/permissions",
        headers=admin_headers,
        json={"permission_codes": current},
    )
    assert restored.status_code == 200
    again = client.get("/internal/v1/auth/me", headers=analyst_headers)
    assert "audit:read" not in again.json()["user"]["permissions"]


def test_candidates_and_resolve_follow_role_and_org(env) -> None:
    app, database, _ = env
    client = TestClient(app)
    token = _token(client, "recon01", DEMO_PASSWORD)
    headers = {"Authorization": f"Bearer {token}"}

    candidates = client.get(
        "/internal/v1/candidates", headers=headers, params={"target_role": "analyst"}
    )
    assert candidates.status_code == 200
    names = {item["display_name"] for item in candidates.json()["items"]}
    assert names == {"分析员甲", "分析员乙"}
    assert all(item["organization_code"] == "ORG-ANA" for item in candidates.json()["items"])

    exec_ids = [item["user_id"] for item in client.get(
        "/internal/v1/candidates", headers=headers, params={"target_role": "executor"}
    ).json()["items"]]
    assert len(exec_ids) == 2

    resolved = client.post(
        "/internal/v1/users/resolve",
        headers=headers,
        json={"user_ids": [exec_ids[0], "00000000-0000-0000-0000-000000000000"], "required_role": "executor"},
    )
    assert resolved.status_code == 200
    flags = {item["user_id"]: item["valid"] for item in resolved.json()["items"]}
    assert flags[exec_ids[0]] is True
    assert flags["00000000-0000-0000-0000-000000000000"] is False


def test_public_keys_exposes_rs256_key(env) -> None:
    app, _, _ = env
    client = TestClient(app)
    body = client.get("/internal/v1/auth/public-keys").json()
    assert body["keys"][0]["alg"] == "RS256"
    assert "BEGIN PUBLIC KEY" in body["keys"][0]["public_key_pem"]
