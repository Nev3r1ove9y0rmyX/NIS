"""执行服务路由（内部 /internal/v1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app import service
from app.payloads import (
    AssignmentCreateBatch,
    CompleteRequest,
    RejectRequest,
    TransitionRequest,
)
from nis_shared.auth import Principal, get_principal, require_permission
from nis_shared.errors import ApiError
from nis_shared.pagination import PageQuery, page_query
from nis_shared.storage import resolve_storage_path

router = APIRouter(tags=["执行分配"])


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
        resource_type="execution_assignment",
        resource_id=resource_id,
        error_code=error_code,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def _write_back(
    request: Request, item, principal: Principal  # noqa: ANN001
) -> None:
    """把个人状态回写给决策服务；失败只告警，不阻断执行员的实际操作。"""

    client = getattr(request.app.state, "decision", None)
    if client is None:
        return
    try:
        client.apply_assignment_state(
            item.command_id,
            assignment_id=item.id,
            executor_id=item.executor_id,
            status=item.status,
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )
    except ApiError as exc:
        _audit(
            request,
            "execution.state_writeback",
            "failure",
            principal=principal,
            resource_id=item.id,
            error_code=exc.code,
            details={"status": item.status},
        )


@router.post("/internal/v1/assignments", status_code=201, summary="批量创建个人分配（幂等）")
def create_assignments(
    payload: AssignmentCreateBatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    items = service.create_batch(
        db,
        command_id=payload.command_id,
        command_title=payload.command_title,
        command_content=payload.command_content,
        priority=payload.priority,
        deadline=payload.deadline,
        executor_ids=payload.executor_ids,
        created_by=payload.created_by,
    )
    _audit(
        request,
        "execution_assignment.create",
        "success",
        principal=principal,
        details={"command_id": payload.command_id, "count": len(items)},
    )
    return {
        "command_id": payload.command_id,
        "items": [service.assignment_view(item) for item in items],
    }


@router.get("/internal/v1/assignments", summary="本人执行分配列表")
def list_assignments(
    request: Request,
    executor_id: str = Query(min_length=36, max_length=36),
    status: str | None = Query(default=None),
    page: PageQuery = Depends(page_query),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:read_assigned")),
) -> dict:
    if principal.user_id != executor_id:
        raise ApiError("FORBIDDEN", "只能查询分配给自己的执行任务")
    return service.list_assignments(
        db, executor_id=principal.user_id, status=status, page=page.page, page_size=page.page_size
    )


@router.get("/internal/v1/assignments/{assignment_id}", summary="执行分配详情")
def get_assignment(
    assignment_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:read_assigned")),
) -> dict:
    item = service.get_assignment(db, assignment_id)
    service.ensure_owner(item, principal.user_id)
    return service.assignment_view(item)


@router.post("/internal/v1/assignments/{assignment_id}/accept", summary="接收指令")
def accept(
    assignment_id: str,
    payload: TransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("execution:respond")),
) -> dict:
    item = service.get_assignment(db, assignment_id)
    service.ensure_owner(item, principal.user_id)
    try:
        updated = service.accept(
            db, item, actor_id=principal.user_id, expected_version=payload.expected_version
        )
    except ApiError as exc:
        _audit(request, "execution_assignment.accept", "denied", principal=principal, resource_id=assignment_id, error_code=exc.code)
        raise
    _write_back(request, updated, principal)
    _audit(request, "execution_assignment.accept", "success", principal=principal, resource_id=assignment_id)
    return service.assignment_view(updated)


@router.post("/internal/v1/assignments/{assignment_id}/reject", summary="拒绝指令")
def reject(
    assignment_id: str,
    payload: RejectRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("execution:respond")),
) -> dict:
    item = service.get_assignment(db, assignment_id)
    service.ensure_owner(item, principal.user_id)
    try:
        updated = service.reject(
            db,
            item,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
    except ApiError as exc:
        _audit(request, "execution_assignment.reject", "denied", principal=principal, resource_id=assignment_id, error_code=exc.code)
        raise
    _write_back(request, updated, principal)
    _audit(
        request,
        "execution_assignment.reject",
        "success",
        principal=principal,
        resource_id=assignment_id,
        details={"reason": payload.reason},
    )
    return service.assignment_view(updated)


@router.post("/internal/v1/assignments/{assignment_id}/start", summary="开始执行")
def start(
    assignment_id: str,
    payload: TransitionRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("execution:update")),
) -> dict:
    item = service.get_assignment(db, assignment_id)
    service.ensure_owner(item, principal.user_id)
    try:
        updated = service.start(
            db, item, actor_id=principal.user_id, expected_version=payload.expected_version
        )
    except ApiError as exc:
        _audit(request, "execution_assignment.start", "denied", principal=principal, resource_id=assignment_id, error_code=exc.code)
        raise
    _write_back(request, updated, principal)
    _audit(request, "execution_assignment.start", "success", principal=principal, resource_id=assignment_id)
    return service.assignment_view(updated)


@router.post("/internal/v1/assignments/{assignment_id}/complete", summary="提交执行结果")
def complete(
    assignment_id: str,
    payload: CompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("execution:submit")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    item = service.get_assignment(db, assignment_id)
    service.ensure_owner(item, principal.user_id)
    dedupe = idempotency_key or getattr(request.state, "request_id", None)
    try:
        updated = service.complete(
            db,
            item,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            outcome=payload.outcome,
            summary=payload.summary,
            detail=payload.detail,
            evidence=[entry.model_dump() for entry in payload.evidence],
            idempotency_key=dedupe,
        )
    except ApiError as exc:
        _audit(
            request,
            "execution_assignment.complete",
            "denied",
            principal=principal,
            resource_id=assignment_id,
            error_code=exc.code,
        )
        raise
    _write_back(request, updated, principal)
    _audit(
        request,
        "execution_assignment.complete",
        "success",
        principal=principal,
        resource_id=assignment_id,
        details={"outcome": payload.outcome, "evidence": len(payload.evidence)},
    )
    return service.assignment_view(updated)


@router.get("/internal/v1/commands/{command_id}/summary", summary="指令执行情况汇总")
def command_summary(
    command_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    items = service.summary_items(db, command_id)
    if not items:
        raise ApiError("RESOURCE_NOT_FOUND", "该指令没有执行分配")
    aggregate = None
    client = getattr(request.app.state, "decision", None)
    if client is not None:
        # 总体状态只由决策服务计算（D-01），这里只做读取透传
        try:
            aggregate = client.get_status(
                command_id,
                token=principal.raw_token,
                request_id=getattr(request.state, "request_id", None),
            ).get("status")
        except ApiError:
            aggregate = None
    return {
        "command_id": command_id,
        "aggregate_status": aggregate,
        "items": items,
    }

@router.get(
    "/internal/v1/assignments/{assignment_id}/evidence/{evidence_id}",
    summary="下载执行证据（受控目录，决策 D-02）",
)
def download_evidence(
    assignment_id: str,
    evidence_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:read_assigned")),
) -> FileResponse:
    item = service.get_assignment(db, assignment_id)
    try:
        service.ensure_owner(item, principal.user_id)
    except ApiError:
        _audit(
            request,
            "evidence.download",
            "denied",
            principal=principal,
            resource_id=evidence_id,
            error_code="RESOURCE_NOT_FOUND",
            details={"assignment_id": assignment_id},
        )
        raise

    evidence = next((entry for entry in item.evidence if entry.id == evidence_id), None)
    if evidence is None:
        raise ApiError("RESOURCE_NOT_FOUND", "证据文件不存在")

    path = resolve_storage_path(evidence.storage_ref)
    _audit(
        request,
        "evidence.download",
        "success",
        principal=principal,
        resource_id=evidence_id,
        details={"assignment_id": assignment_id, "sha256": evidence.sha256},
    )
    return FileResponse(path, media_type=evidence.media_type, filename=evidence.file_name)
