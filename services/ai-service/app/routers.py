"""AI 建议服务路由（内部 /internal/v1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app import service
from app.payloads import SuggestionCreate, SuggestionDecision
from nis_shared.auth import Principal, get_principal, require_permission
from nis_shared.pagination import PageQuery, page_query

router = APIRouter(tags=["AI 建议"])


def get_db(request: Request):  # noqa: ANN201
    database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()


def _audit(
    request: Request,
    action: str,
    result: str,
    *,
    principal: Principal | None = None,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    audit.write(
        event_type="user_operation",
        action=action,
        result=result,
        request_id=getattr(request.state, "request_id", ""),
        actor_user_id=principal.user_id if principal else None,
        actor_role=principal.role_context if principal else None,
        resource_type="ai_suggestion",
        resource_id=resource_id,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def _business_context(request: Request, principal: Principal, payload) -> str:  # noqa: ANN001
    """读取业务对象正文，作为模型提示词素材；读不到就返回空串（不影响请求）。"""

    try:
        if payload.business_object_type == "recon_record":
            client = getattr(request.app.state, "recon", None)
            if client is None:
                return ""
            view = client.authorized_view(
                payload.business_object_id,
                requester_id=principal.user_id,
                purpose="ai",
                token=principal.raw_token,
                request_id=getattr(request.state, "request_id", None),
            )
            record = view.get("record") or view
            return (
                f"侦察记录标题：{record.get('title', '')}\n"
                f"侦察正文：{record.get('content', '')}\n"
                f"来源：{record.get('source_type', '')} | 可信度：{record.get('credibility', '')}"
            )
        if payload.business_object_type == "analysis_report":
            client = getattr(request.app.state, "analysis", None)
            if client is None:
                return ""
            view = client.authorized_view(
                payload.business_object_id,
                requester_id=principal.user_id,
                purpose="ai",
                token=principal.raw_token,
                request_id=getattr(request.state, "request_id", None),
            )
            report = view.get("report") or view
            return (
                f"分析报告标题：{report.get('title', '')}\n"
                f"关键发现：{report.get('key_findings', '')}\n"
                f"关联关系：{report.get('relations', '') or '无'}\n"
                f"建议措施：{report.get('recommended_actions', '') or '无'}"
            )
    except Exception as exc:  # noqa: BLE001 - 取不到内容时降级为无上下文
        print(f"[ai] 读取业务对象内容失败，按无上下文生成：{exc}", flush=True)
    return ""


@router.post("/internal/v1/suggestions", summary="请求 AI 建议（可降级）")
def create_suggestion(
    payload: SuggestionCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("ai:suggest")),
) -> dict:
    if principal.user_id != payload.requested_by:
        from nis_shared.errors import ApiError

        raise ApiError("FORBIDDEN", "令牌主体与请求声明的用户不一致")
    context = _business_context(request, principal, payload)
    ai_request, suggestion = service.create_suggestion(
        db,
        stage=payload.stage,
        business_object_type=payload.business_object_type,
        business_object_id=payload.business_object_id,
        suggestion_type=payload.suggestion_type,
        requested_by=principal.user_id,
        context=context,
    )
    _audit(
        request,
        "ai.suggestion.created",
        "success",
        principal=principal,
        resource_id=suggestion.id,
        details={"stage": payload.stage, "suggestion_type": payload.suggestion_type},
    )
    return service.suggestion_view(suggestion, ai_request)


@router.get("/internal/v1/suggestions", summary="按业务对象查建议")
def list_suggestions(
    business_object_type: str = Query(
        pattern="^(recon_record|analysis_report|command|assignment)$"
    ),
    business_object_id: str = Query(min_length=36, max_length=36),
    page: PageQuery = Depends(page_query),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_permission("ai:suggest")),
) -> dict:
    return service.list_suggestions(
        db,
        business_object_type=business_object_type,
        business_object_id=business_object_id,
        page=page.page,
        page_size=page.page_size,
    )


@router.get("/internal/v1/suggestions/{suggestion_id}", summary="建议详情")
def get_suggestion(
    suggestion_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_permission("ai:suggest")),
) -> dict:
    suggestion, ai_request = service.get_suggestion(db, suggestion_id)
    return service.suggestion_view(suggestion, ai_request)


@router.post("/internal/v1/suggestions/{suggestion_id}/decision", summary="人工接受/修改/拒绝")
def decide_suggestion(
    suggestion_id: str,
    payload: SuggestionDecision,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("ai:suggest")),
) -> dict:
    from nis_shared.errors import ApiError

    if principal.user_id != payload.confirmed_by:
        raise ApiError("FORBIDDEN", "确认人必须是当前登录用户")
    suggestion, ai_request = service.get_suggestion(db, suggestion_id)
    updated = service.decide(
        db,
        suggestion,
        decision=payload.decision,
        confirmed_by=principal.user_id,
        edited_content=payload.edited_content,
        note=payload.note,
    )
    _audit(
        request,
        "ai.suggestion.decided",
        "success",
        principal=principal,
        resource_id=suggestion_id,
        details={"decision": payload.decision, "note": payload.note},
    )
    return service.suggestion_view(updated, ai_request)
