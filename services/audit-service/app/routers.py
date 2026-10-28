"""审计服务路由：只追加的事件写入。

事件号由数据库自增生成，业务账号没有 UPDATE/DELETE 权限（决策 D-06）。
幂等口径：同一 ``request_id`` + ``service`` + ``action`` + ``result`` 视为同一条事件，
重复投递返回已存在的记录而不是再插一行（关键提交可安全重试）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, AuditTraceIndex
from nis_shared.errors import ApiError
from nis_shared.models import utcnow

router = APIRouter(tags=["审计事件"])


class AuditEventCreate(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    service: str = Field(min_length=1, max_length=64)
    event_type: str = Field(pattern="^(user_operation|system_event|security_event)$")
    action: str = Field(min_length=1, max_length=64)
    result: str = Field(pattern="^(success|failure|denied)$")
    actor_user_id: str | None = Field(default=None, max_length=36)
    actor_role: str | None = Field(default=None, max_length=32)
    actor_organization_id: str | None = Field(default=None, max_length=36)
    resource_type: str | None = Field(default=None, max_length=64)
    resource_id: str | None = Field(default=None, max_length=36)
    error_code: str | None = Field(default=None, max_length=64)
    source_ip: str | None = Field(default=None, max_length=64)
    user_agent: str | None = Field(default=None, max_length=300)
    service_identity: str | None = Field(default=None, max_length=64)
    details: dict[str, Any] | None = None
    payload_digest: str | None = Field(default=None, max_length=64)


def get_db(request: Request):  # noqa: ANN201
    database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()


def _to_view(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": str(event.id),
        "sequence": event.id,
        "request_id": event.request_id,
        "occurred_at": event.occurred_at.replace(microsecond=0).isoformat() + "Z",
        "service": event.service,
        "event_type": event.event_type,
        "actor_user_id": event.actor_user_id,
        "actor_role": event.actor_role,
        "actor_organization_id": event.actor_organization_id,
        "action": event.action,
        "resource_type": event.resource_type,
        "resource_id": event.resource_id,
        "result": event.result,
        "error_code": event.error_code,
        "source_ip": event.source_ip,
        "user_agent": event.user_agent,
        "service_identity": event.service_identity,
        "details": event.details,
    }


@router.post("/internal/v1/audit-events", status_code=201, summary="追加审计事件（幂等）")
def append_event(
    payload: AuditEventCreate,
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    existing = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.request_id == payload.request_id)
        .where(AuditEvent.service == payload.service)
        .where(AuditEvent.action == payload.action)
        .where(AuditEvent.result == payload.result)
        .order_by(AuditEvent.id)
    ).first()
    if existing is not None:
        return _to_view(existing)

    service = payload.service
    event = AuditEvent(
        request_id=payload.request_id,
        occurred_at=utcnow(),
        service=service,
        event_type=payload.event_type,
        actor_user_id=payload.actor_user_id,
        actor_role=payload.actor_role,
        actor_organization_id=payload.actor_organization_id,
        action=payload.action,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        result=payload.result,
        error_code=payload.error_code,
        source_ip=payload.source_ip,
        user_agent=payload.user_agent,
        service_identity=payload.service_identity or service,
        details=payload.details,
        payload_digest=payload.payload_digest,
    )
    db.add(event)
    db.flush()

    trace = db.get(AuditTraceIndex, payload.request_id)
    if trace is None:
        db.add(
            AuditTraceIndex(
                request_id=payload.request_id,
                root_action=payload.action,
                started_at=event.occurred_at,
                event_count=1,
                outcome=payload.result,
            )
        )
    else:
        trace.event_count = int(trace.event_count or 0) + 1
        trace.outcome = payload.result
    if payload.result != "failure" and trace is not None:
        trace.completed_at = event.occurred_at
    db.commit()
    db.refresh(event)
    if idempotency_key is None:
        # 没有幂等键也允许写入；上面按 request_id+action 的去重已覆盖常见重试
        pass
    return _to_view(event)
