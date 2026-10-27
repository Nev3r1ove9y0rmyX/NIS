"""审计事件写入用例（Issue #8 依赖：越权与登录事件必须能落库）。

审计查询与调用链还原属于 Issue #11，这里只验证「只追加 + 幂等 + 追踪索引」。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service

REQUEST_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"


@pytest.fixture
def audit_client():
    import_service("audit-service")
    from nis_shared.db import Database

    database = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(database)

    main = import_service("audit-service")[1]
    app = main.app
    app.state.database = database
    yield TestClient(app), database
    database.engine.dispose()


def _event(**overrides) -> dict:  # noqa: ANN003
    payload = {
        "request_id": REQUEST_ID,
        "service": "iam-service",
        "event_type": "security_event",
        "action": "auth.permission.denied",
        "result": "denied",
        "actor_user_id": "5b1f0a7e-0f5a-4d9e-9d1f-2c3b4a5d6e7f",
        "actor_role": "reconnaissance",
        "resource_type": "user",
        "source_ip": "10.0.1.101",
        "details": {"permission": "iam:manage"},
    }
    payload.update(overrides)
    return payload


def test_append_event_persists_and_returns_view(audit_client) -> None:
    client, database = audit_client
    response = client.post(
        "/internal/v1/audit-events",
        json=_event(),
        headers={"Idempotency-Key": "k-1", "X-Request-ID": REQUEST_ID},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["request_id"] == REQUEST_ID
    assert body["result"] == "denied"
    assert body["occurred_at"].endswith("Z")
    assert int(body["sequence"]) >= 1

    from sqlalchemy import select

    from app.models import AuditEvent, AuditTraceIndex

    with database.session() as db:
        events = db.scalars(select(AuditEvent)).all()
        assert len(events) == 1
        trace = db.get(AuditTraceIndex, REQUEST_ID)
        assert trace is not None and trace.event_count == 1


def test_repeated_delivery_is_idempotent(audit_client) -> None:
    client, database = audit_client
    first = client.post("/internal/v1/audit-events", json=_event())
    second = client.post("/internal/v1/audit-events", json=_event())
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    from sqlalchemy import select

    from app.models import AuditEvent

    with database.session() as db:
        assert len(db.scalars(select(AuditEvent)).all()) == 1


def test_distinct_actions_share_trace(audit_client) -> None:
    client, database = audit_client
    client.post("/internal/v1/audit-events", json=_event())
    client.post(
        "/internal/v1/audit-events",
        json=_event(service="recon-service", action="recon_record.submit", result="success"),
    )

    from sqlalchemy import select

    from app.models import AuditEvent, AuditTraceIndex

    with database.session() as db:
        events = db.scalars(select(AuditEvent).order_by(AuditEvent.id)).all()
        assert [e.action for e in events] == ["auth.permission.denied", "recon_record.submit"]
        trace = db.get(AuditTraceIndex, REQUEST_ID)
        assert trace.event_count == 2
        assert trace.outcome == "success"


def test_invalid_event_is_rejected(audit_client) -> None:
    client, _ = audit_client
    bad = client.post("/internal/v1/audit-events", json=_event(result="maybe"))
    assert bad.status_code == 422
    assert bad.json()["code"] == "VALIDATION_ERROR"

    missing = client.post("/internal/v1/audit-events", json={"request_id": REQUEST_ID})
    assert missing.status_code == 422
