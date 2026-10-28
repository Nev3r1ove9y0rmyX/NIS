"""侦察服务路由（内部 /internal/v1，仅容器网络可达）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app import service
from app.payloads import (
    AnalysisStateUpdate,
    ConfirmSubmission,
    MarkCompensation,
    ReconRecordCreate,
    ReconRecordPatch,
    ReconSubmit,
)
from nis_shared.auth import Principal, get_principal, require_permission
from nis_shared.errors import ApiError
from nis_shared.pagination import PageQuery, page_query

router = APIRouter(tags=["侦察记录"])


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
    resource_type: str = "recon_record",
    resource_id: str | None = None,
    error_code: str | None = None,
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
        resource_type=resource_type,
        resource_id=resource_id,
        error_code=error_code,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def _assert_self(principal: Principal, claimed_user_id: str, field: str) -> None:
    """内部接口不能凭请求体冒充别人：令牌主体必须与声明的用户一致。"""

    if principal.user_id != claimed_user_id:
        raise ApiError(
            "FORBIDDEN",
            "令牌主体与请求声明的用户不一致",
            details={"field": field},
        )


@router.get("/internal/v1/recon-records", summary="查看本人或被指派的侦察记录")
def list_records(
    request: Request,
    viewer_user_id: str = Query(min_length=36, max_length=36),
    status: str | None = Query(default=None),
    page: PageQuery = Depends(page_query),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("recon:read_assigned")),
) -> dict:
    _assert_self(principal, viewer_user_id, "viewer_user_id")
    return service.list_records(
        db, viewer_id=principal.user_id, status=status, page=page.page, page_size=page.page_size
    )


@router.post("/internal/v1/recon-records", status_code=201, summary="创建侦察草稿")
def create_record(
    payload: ReconRecordCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("recon:create")),
) -> dict:
    _assert_self(principal, payload.owner_id, "owner_id")
    organization_id = payload.organization_id or principal.organization_id
    if not organization_id:
        raise ApiError("INVALID_REQUEST", "缺少组织信息")
    record = service.create_record(
        db,
        owner_id=principal.user_id,
        organization_id=organization_id,
        title=payload.title,
        source_type=payload.source_type,
        source_ref=payload.source_ref,
        content=payload.content,
        credibility=payload.credibility,
        priority=payload.priority,
        evidence=[item.model_dump() for item in payload.evidence],
    )
    _audit(
        request,
        "recon_record.create",
        "success",
        principal=principal,
        resource_id=record.id,
        details={"record_no": record.record_no},
    )
    return service.record_view(record)


@router.get("/internal/v1/recon-records/{record_id}", summary="侦察记录详情")
def get_record(
    record_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("recon:read_assigned")),
) -> dict:
    record = service.get_record(db, record_id)
    try:
        service.ensure_visible(record, principal.user_id)
    except ApiError:
        _audit(
            request,
            "recon_record.read",
            "denied",
            principal=principal,
            resource_id=record_id,
            error_code="RESOURCE_NOT_FOUND",
        )
        raise
    return service.record_view(record)


@router.patch("/internal/v1/recon-records/{record_id}", summary="编辑草稿")
def update_record(
    record_id: str,
    payload: ReconRecordPatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("recon:edit_own_draft")),
) -> dict:
    record = service.get_record(db, record_id)
    try:
        updated = service.update_record(
            db,
            record,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            changes=payload.model_dump(exclude={"expected_version"}),
        )
    except ApiError as exc:
        _audit(
            request,
            "recon_record.update",
            "denied",
            principal=principal,
            resource_id=record_id,
            error_code=exc.code,
            details=exc.details,
        )
        raise
    _audit(request, "recon_record.update", "success", principal=principal, resource_id=record_id)
    return service.record_view(updated)


@router.post("/internal/v1/recon-records/{record_id}/submit", summary="提交并指派分析员")
def submit_record(
    record_id: str,
    payload: ReconSubmit,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("recon:submit")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    record = service.get_record(db, record_id)

    # 接收人二次校验：必须存在、启用且具备分析员角色（防前端伪造）
    iam = getattr(request.app.state, "iam", None)
    if iam is not None:
        resolved = iam.resolve(
            payload.analyst_ids,
            "analyst",
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )
        invalid = [item["user_id"] for item in resolved if not item.get("valid")]
        if invalid:
            _audit(
                request,
                "recon_record.submit",
                "denied",
                principal=principal,
                resource_id=record_id,
                error_code="INVALID_REQUEST",
                details={"invalid_analyst_ids": invalid},
            )
            raise ApiError(
                "INVALID_REQUEST",
                "存在不可指派的分析员",
                details={"invalid_analyst_ids": invalid},
            )

    dedupe_key = idempotency_key or getattr(request.state, "request_id", None)
    try:
        submitted = service.submit_record(
            db,
            record,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            analyst_ids=payload.analyst_ids,
            priority=payload.priority,
            dedupe_key=dedupe_key,
        )
    except ApiError as exc:
        _audit(
            request,
            "recon_record.submit",
            "denied",
            principal=principal,
            resource_id=record_id,
            error_code=exc.code,
            details=exc.details,
        )
        raise
    _audit(
        request,
        "recon_record.submit",
        "success",
        principal=principal,
        resource_id=record_id,
        details={
            "analyst_ids": payload.analyst_ids,
            "status": submitted.status,
            "idempotent_replay": submitted.last_request_id != dedupe_key,
        },
    )
    return service.record_view(submitted)


@router.post(
    "/internal/v1/recon-records/{record_id}/confirm-submission", summary="确认提交结果（协调器重试）"
)
def confirm_submission(
    record_id: str,
    payload: ConfirmSubmission,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    record = service.get_record(db, record_id)
    updated = service.confirm_submission(
        db, record, actor_id=principal.user_id, expected_version=payload.expected_version
    )
    _audit(
        request,
        "recon_record.confirm_submission",
        "success",
        principal=principal,
        resource_id=record_id,
        details={"status": updated.status},
    )
    return service.record_view(updated)


@router.post(
    "/internal/v1/recon-records/{record_id}/mark-compensation", summary="标记需要人工补偿"
)
def mark_compensation(
    record_id: str,
    payload: MarkCompensation,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    record = service.get_record(db, record_id)
    updated = service.mark_compensation(
        db, record, reason=payload.reason, failed_step=payload.failed_step
    )
    _audit(
        request,
        "recon_record.mark_compensation",
        "failure",
        principal=principal,
        resource_id=record_id,
        error_code="COMPENSATION_REQUIRED",
        details={"failed_step": payload.failed_step, "reason": payload.reason},
    )
    return service.record_view(updated)


@router.get("/internal/v1/recon-records/{record_id}/assignments", summary="指派列表")
def list_assignments(
    record_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(get_principal),
) -> dict:
    record = service.get_record(db, record_id)
    return {"items": [service.assignment_view(item) for item in record.assignments]}


@router.post("/internal/v1/recon-records/{record_id}/analysis-state", summary="回写分析处理状态")
def update_analysis_state(
    record_id: str,
    payload: AnalysisStateUpdate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    record = service.get_record(db, record_id)
    updated = service.update_analysis_state(
        db,
        record,
        analyst_id=payload.analyst_id,
        assignment_status=payload.assignment_status,
        reject_reason=payload.reject_reason,
    )
    _audit(
        request,
        "recon_record.analysis_state",
        "success",
        principal=principal,
        resource_id=record_id,
        details={"analyst_id": payload.analyst_id, "status": payload.assignment_status},
    )
    return service.record_view(updated)


@router.get("/internal/v1/recon-records/{record_id}/authorized-view", summary="跨服务授权读取")
def authorized_view(
    record_id: str,
    requester_user_id: str = Query(min_length=36, max_length=36),
    purpose: str = Query(pattern="^(analysis|decision|audit)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    _assert_self(principal, requester_user_id, "requester_user_id")
    record = service.get_record(db, record_id)
    return service.authorized_view(db, record, requester_id=principal.user_id, purpose=purpose)
