"""Gateway 审计与 AI 路由（/api/v1）。

审计查询要求 ``audit:read``；AI 建议要求 ``ai:suggest``，且建议只是建议——
处理动作（accept/edit/reject）必须带确认人，由 ai-service 记录。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.proxy import forward
from nis_shared.auth import Principal, get_principal
from nis_shared.errors import ApiError

router = APIRouter(prefix="/api/v1", tags=["审计与 AI"])

STAGE = "^(recon|analysis|decision|execution)$"
OBJECT_TYPE = "^(recon_record|analysis_report|command|assignment)$"
SUGGESTION_TYPE = (
    "^(summary|classification|missing_field_hint|entity_relation|risk_assessment|action_options|conflict_hint)$"
)


class SuggestionRequest(BaseModel):
    stage: str = Field(pattern=STAGE)
    business_object_type: str = Field(pattern=OBJECT_TYPE)
    business_object_id: str = Field(min_length=36, max_length=36)
    suggestion_type: str = Field(pattern=SUGGESTION_TYPE)


class SuggestionDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(accepted|edited|rejected)$")
    edited_content: dict | None = None
    note: str | None = Field(default=None, max_length=500)


def _principal(request: Request, permission: str) -> Principal:
    principal = get_principal(request)
    if not principal.has(permission):
        audit = getattr(request.app.state, "audit", None)
        if audit is not None:
            audit.write(
                event_type="security_event",
                action="gateway.permission.denied",
                result="denied",
                request_id=getattr(request.state, "request_id", ""),
                actor_user_id=principal.user_id,
                actor_role=principal.role_context,
                error_code="FORBIDDEN",
                source_ip=request.client.host if request.client else None,
                details={"permission": permission, "path": request.url.path},
            )
        raise ApiError("FORBIDDEN", "没有执行该操作的权限", details={"permission": permission})
    return principal


# --------------------------------------------------------------------------- 审计


@router.get("/audit-events", summary="审计事件查询")
def list_audit_events(
    request: Request,
    resource_type: str | None = Query(default=None),
    resource_id: str | None = Query(default=None),
    request_id: str | None = Query(default=None),
    actor_user_id: str | None = Query(default=None),
    result: str | None = Query(default=None, pattern="^(success|failure|denied)$"),
    from_ts: str | None = Query(default=None, alias="from"),
    to_ts: str | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    _principal(request, "audit:read")
    code, payload = forward(
        request,
        "GET",
        "/internal/v1/audit-events",
        upstream="audit",
        params={
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "actor_user_id": actor_user_id,
            "result": result,
            "from": from_ts,
            "to": to_ts,
            "page": page,
            "page_size": page_size,
        },
    )
    return JSONResponse(payload, status_code=code)


@router.get("/audit-events/traces/{request_id}", summary="按请求 ID 还原调用链")
def get_audit_trace(request_id: str, request: Request) -> JSONResponse:
    _principal(request, "audit:read")
    code, payload = forward(
        request, "GET", f"/internal/v1/traces/{request_id}", upstream="audit"
    )
    return JSONResponse(payload, status_code=code)


# --------------------------------------------------------------------------- AI


@router.post("/ai/suggestions", summary="请求 AI 建议（可降级）")
def create_suggestion(payload: SuggestionRequest, request: Request) -> JSONResponse:
    principal = _principal(request, "ai:suggest")
    body = payload.model_dump()
    body["requested_by"] = principal.user_id
    code, suggestion = forward(
        request, "POST", "/internal/v1/suggestions", upstream="ai", json_body=body
    )
    return JSONResponse(suggestion, status_code=code)


@router.get("/ai/suggestions/{suggestion_id}", summary="AI 建议详情")
def get_suggestion(suggestion_id: str, request: Request) -> JSONResponse:
    _principal(request, "ai:suggest")
    code, suggestion = forward(
        request, "GET", f"/internal/v1/suggestions/{suggestion_id}", upstream="ai"
    )
    return JSONResponse(suggestion, status_code=code)


@router.post("/ai/suggestions/{suggestion_id}/decision", summary="人工处理 AI 建议")
def decide_suggestion(
    suggestion_id: str, payload: SuggestionDecisionRequest, request: Request
) -> JSONResponse:
    principal = _principal(request, "ai:suggest")
    body = payload.model_dump(exclude_none=True)
    body["confirmed_by"] = principal.user_id
    code, suggestion = forward(
        request,
        "POST",
        f"/internal/v1/suggestions/{suggestion_id}/decision",
        upstream="ai",
        json_body=body,
    )
    return JSONResponse(suggestion, status_code=code)
