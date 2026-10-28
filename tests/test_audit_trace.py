"""审计查询、调用链还原与 AI 建议用例（Issue #11）。"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service
from test_auth import ADMIN_PASSWORD, DEMO_PASSWORD, AsgiBridge

API = "/api/v1"
REQUEST_ID = "9a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def write(self, **kwargs) -> bool:  # noqa: ANN003
        self.events.append(kwargs)
        return True


@pytest.fixture
def stack(monkeypatch):
    from nis_shared.clients import IamClient, InternalClient
    from nis_shared.db import Database

    monkeypatch.setenv("AI_ENABLED", "true")

    import_service("iam-service")
    iam_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(iam_db)
    seed = importlib.import_module("app.seed")
    seed.seed(iam_db, admin_password=ADMIN_PASSWORD, demo_password=DEMO_PASSWORD)
    iam_app = importlib.import_module("app.main").app
    iam_app.state.database = iam_db
    iam_app.state.audit = RecordingAudit()
    iam_bridge = AsgiBridge(iam_app)

    import_service("audit-service")
    audit_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(audit_db)
    audit_app = importlib.import_module("app.main").app
    audit_app.state.database = audit_db
    audit_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    audit_bridge = AsgiBridge(audit_app)

    import_service("ai-service")
    ai_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(ai_db)
    ai_app = importlib.import_module("app.main").app
    ai_app.state.database = ai_db
    ai_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    ai_app.state.audit = RecordingAudit()
    ai_bridge = AsgiBridge(ai_app)

    import_service("api-gateway")
    gateway_app = importlib.import_module("app.main").app
    gateway_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.iam_http = InternalClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.audit_http = InternalClient("http://audit-service:8007", transport=audit_bridge)
    gateway_app.state.ai_http = InternalClient("http://ai-service:8006", transport=ai_bridge)
    gateway_app.state.audit = RecordingAudit()

    return {
        "client": TestClient(gateway_app),
        "audit_client": TestClient(audit_app),
        "ai_client": TestClient(ai_app),
    }


def login(client: TestClient, username: str, password: str = DEMO_PASSWORD) -> str:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token: str, role: str | None = None, request_id: str | None = None) -> dict:
    result = {"Authorization": f"Bearer {token}"}
    if role:
        result["X-Role-Context"] = role
    if request_id:
        result["X-Request-ID"] = request_id
    return result


def _event(**overrides) -> dict:  # noqa: ANN003
    payload = {
        "request_id": REQUEST_ID,
        "service": "recon-service",
        "event_type": "user_operation",
        "action": "recon_record.submit",
        "result": "success",
        "actor_user_id": "5b1f0a7e-0f5a-4d9e-9d1f-2c3b4a5d6e7f",
        "actor_role": "reconnaissance",
        "resource_type": "recon_record",
        "resource_id": "0b6f8f7e-1111-4222-8333-444455556666",
        "source_ip": "10.0.1.103",
        "details": {"record_no": "REC-20261027-0001"},
    }
    payload.update(overrides)
    return payload


def test_audit_query_requires_permission(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    denied = client.get(f"{API}/audit-events", headers=headers(recon_token))
    assert denied.status_code == 403
    assert denied.json()["details"]["permission"] == "audit:read"

    admin_token = login(client, "admin", ADMIN_PASSWORD)
    allowed = client.get(f"{API}/audit-events", headers=headers(admin_token, "administrator"))
    assert allowed.status_code == 200
    assert "items" in allowed.json()


def test_audit_event_filters(stack) -> None:
    audit_client: TestClient = stack["audit_client"]
    audit_client.post("/internal/v1/audit-events", json=_event())
    audit_client.post(
        "/internal/v1/audit-events",
        json=_event(request_id="11111111-2222-4333-8444-555555555555", service="decision-service",
                    action="command.issue", result="denied", actor_role="decision_maker",
                    resource_type="command", resource_id="11111111-3333-4444-8555-666666666666"),
    )

    client = stack["client"]
    admin = login(client, "admin", ADMIN_PASSWORD)
    me = headers(admin, "administrator")

    by_result = client.get(f"{API}/audit-events", headers=me, params={"result": "denied"})
    assert by_result.status_code == 200
    assert by_result.json()["total"] == 1
    assert by_result.json()["items"][0]["code" if False else "action"] == "command.issue"

    by_resource = client.get(
        f"{API}/audit-events", headers=me, params={"resource_type": "recon_record"}
    )
    assert by_resource.json()["total"] == 1

    by_request = client.get(f"{API}/audit-events", headers=me, params={"request_id": REQUEST_ID})
    assert by_request.json()["total"] == 1


def test_trace_restores_cross_service_chain(stack) -> None:
    """同一个 request_id 的多服务事件可以按顺序还原（Issue #11 核心验收）。"""

    audit_client: TestClient = stack["audit_client"]
    audit_client.post("/internal/v1/audit-events", json=_event())
    audit_client.post(
        "/internal/v1/audit-events",
        json=_event(service="analysis-service", action="analysis_report.create", resource_type="analysis_report"),
    )
    audit_client.post(
        "/internal/v1/audit-events",
        json=_event(service="decision-service", action="command.issue", resource_type="command"),
    )

    client = stack["client"]
    admin = login(client, "admin", ADMIN_PASSWORD)
    trace = client.get(
        f"{API}/audit-events/traces/{REQUEST_ID}", headers=headers(admin, "administrator")
    )
    assert trace.status_code == 200, trace.text
    body = trace.json()
    assert body["request_id"] == REQUEST_ID
    assert body["event_count"] == 3
    assert [event["service"] for event in body["events"]] == [
        "recon-service",
        "analysis-service",
        "decision-service",
    ]
    assert body["started_at"].endswith("Z")
    assert body["outcome"] == "success"

    missing = client.get(
        f"{API}/audit-events/traces/00000000-0000-4000-8000-000000000000",
        headers=headers(admin, "administrator"),
    )
    assert missing.status_code == 404


def test_trace_requires_permission(stack) -> None:
    client = stack["client"]
    analyst = login(client, "analyst01")
    response = client.get(f"{API}/audit-events/traces/{REQUEST_ID}", headers=headers(analyst))
    assert response.status_code == 403


def test_event_has_required_fields(stack) -> None:
    """每条事件必须含操作者、角色、动作、对象、结果、时间、来源 IP。"""

    audit_client: TestClient = stack["audit_client"]
    created = audit_client.post("/internal/v1/audit-events", json=_event())
    assert created.status_code == 201
    body = created.json()
    for field in (
        "actor_user_id",
        "actor_role",
        "action",
        "resource_type",
        "resource_id",
        "result",
        "occurred_at",
        "source_ip",
        "request_id",
    ):
        assert body.get(field), f"缺少 {field}"
    assert "password" not in created.text.lower()


# --------------------------------------------------------------------------- AI


def test_ai_suggestion_requires_human_confirmation(stack) -> None:
    client = stack["client"]
    recon = login(client, "recon01")

    created = client.post(
        f"{API}/ai/suggestions",
        headers=headers(recon),
        json={
            "stage": "recon",
            "business_object_type": "recon_record",
            "business_object_id": "0b6f8f7e-1111-4222-8333-444455556666",
            "suggestion_type": "summary",
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["status"] == "pending"
    assert body["model_name"] == "nis-rule-based"
    assert body["human_confirmed_by"] is None
    suggestion_id = body["id"]

    decided = client.post(
        f"{API}/ai/suggestions/{suggestion_id}/decision",
        headers=headers(recon),
        json={"decision": "accepted"},
    )
    assert decided.status_code == 200, decided.text
    assert decided.json()["status"] == "accepted"
    assert decided.json()["human_confirmed_by"]
    assert decided.json()["human_confirmed_at"]

    again = client.post(
        f"{API}/ai/suggestions/{suggestion_id}/decision",
        headers=headers(recon),
        json={"decision": "rejected"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "WORKFLOW_CONFLICT"


def test_ai_edit_requires_content(stack) -> None:
    client = stack["client"]
    recon = login(client, "recon01")
    suggestion = client.post(
        f"{API}/ai/suggestions",
        headers=headers(recon),
        json={
            "stage": "analysis",
            "business_object_type": "analysis_report",
            "business_object_id": "0b6f8f7e-1111-4222-8333-444455556666",
            "suggestion_type": "risk_assessment",
        },
    ).json()

    bad = client.post(
        f"{API}/ai/suggestions/{suggestion['id']}/decision",
        headers=headers(recon),
        json={"decision": "edited"},
    )
    assert bad.status_code == 400

    good = client.post(
        f"{API}/ai/suggestions/{suggestion['id']}/decision",
        headers=headers(recon),
        json={"decision": "edited", "edited_content": {"risk_level_suggestion": "high"}},
    )
    assert good.status_code == 200
    assert good.json()["edited_content"]["risk_level_suggestion"] == "high"


def test_ai_degrades_when_disabled(stack, monkeypatch) -> None:
    """AI 不可用时返回 503，人工流程不受影响（NFR-AI-001）。"""

    client = stack["client"]
    recon = login(client, "recon01")
    monkeypatch.setenv("AI_ENABLED", "false")

    response = client.post(
        f"{API}/ai/suggestions",
        headers=headers(recon),
        json={
            "stage": "recon",
            "business_object_type": "recon_record",
            "business_object_id": "0b6f8f7e-1111-4222-8333-444455556666",
            "suggestion_type": "summary",
        },
    )
    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"


def test_ai_suggestion_is_audited(stack) -> None:
    client = stack["client"]
    recon = login(client, "recon01")
    client.post(
        f"{API}/ai/suggestions",
        headers=headers(recon),
        json={
            "stage": "decision",
            "business_object_type": "command",
            "business_object_id": "0b6f8f7e-1111-4222-8333-444455556666",
            "suggestion_type": "action_options",
        },
    )
    ai_state = stack["ai_client"].app.state.audit
    assert any(event["action"] == "ai.suggestion.created" for event in ai_state.events)
