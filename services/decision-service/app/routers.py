"""决策服务路由（内部 /internal/v1）。

注意路由声明顺序：``/commands/conflicts`` 必须在 ``/commands/{command_id}`` 之前，
否则会被路径参数抢走。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app import service
from app.payloads import (
    AssignmentState,
    CommandCancel,
    CommandConfirmIssue,
    CommandCreate,
    CommandIssue,
    CommandPatch,
)
from nis_shared.auth import Principal, get_principal, require_permission
from nis_shared.errors import ApiError
from nis_shared.pagination import PageQuery, page_query

router = APIRouter(tags=["决策指令"])


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
    event_type: str = "user_operation",
) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    audit.write(
        event_type=event_type,
        action=action,
        result=result,
        request_id=getattr(request.state, "request_id", ""),
        actor_user_id=principal.user_id if principal else None,
        actor_role=principal.role_context if principal else None,
        resource_type="command",
        resource_id=resource_id,
        error_code=error_code,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def _assert_self(principal: Principal, claimed: str, field: str) -> None:
    if principal.user_id != claimed:
        raise ApiError("FORBIDDEN", "令牌主体与请求声明的用户不一致", details={"field": field})


@router.get("/internal/v1/commands", summary="指令列表")
def list_commands(
    request: Request,
    viewer_user_id: str = Query(min_length=36, max_length=36),
    status: str | None = Query(default=None),
    page: PageQuery = Depends(page_query),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:read_assigned")),
) -> dict:
    _assert_self(principal, viewer_user_id, "viewer_user_id")
    return service.list_commands(
        db, viewer_id=principal.user_id, status=status, page=page.page, page_size=page.page_size
    )


@router.get("/internal/v1/commands/conflicts", summary="下达前冲突检查")
def check_conflicts(
    source_report_id: str = Query(min_length=36, max_length=36),
    objective: str | None = Query(default=None),
    exclude_command_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_permission("command:issue")),
) -> dict:
    return service.check_conflicts(
        db,
        source_report_id=source_report_id,
        objective=objective,
        exclude_command_id=exclude_command_id,
    )


@router.post("/internal/v1/commands", status_code=201, summary="创建指令草稿")
def create_command(
    payload: CommandCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:create")),
) -> dict:
    _assert_self(principal, payload.decision_maker_id, "decision_maker_id")
    if payload.organization_id != (principal.organization_id or payload.organization_id):
        raise ApiError("FORBIDDEN", "只能以本人所属组织创建指令")

    analysis = getattr(request.app.state, "analysis", None)
    if analysis is not None:
        # 指令必须基于一份被指派给本人的分析报告
        analysis.authorized_view(
            payload.source_report_id,
            requester_id=principal.user_id,
            purpose="decision",
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )

    command = service.create_command(
        db,
        decision_maker_id=principal.user_id,
        organization_id=payload.organization_id,
        title=payload.title,
        objective=payload.objective,
        content=payload.content,
        priority=payload.priority,
        deadline=payload.deadline,
        source_report_id=payload.source_report_id,
    )
    _audit(
        request,
        "command.create",
        "success",
        principal=principal,
        resource_id=command.id,
        details={"command_no": command.command_no, "source_report_id": payload.source_report_id},
    )
    return service.command_view(command)


@router.get("/internal/v1/commands/{command_id}", summary="指令详情")
def get_command(
    command_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:read_assigned")),
) -> dict:
    command = service.get_command(db, command_id)
    try:
        service.ensure_visible(command, principal.user_id)
    except ApiError:
        _audit(
            request,
            "command.read",
            "denied",
            principal=principal,
            resource_id=command_id,
            error_code="RESOURCE_NOT_FOUND",
        )
        raise
    return service.command_view(command)


@router.patch("/internal/v1/commands/{command_id}", summary="编辑指令草稿")
def update_command(
    command_id: str,
    payload: CommandPatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:create")),
) -> dict:
    command = service.get_command(db, command_id)
    try:
        updated = service.update_command(
            db,
            command,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            changes=payload.model_dump(exclude={"expected_version"}),
        )
    except ApiError as exc:
        _audit(request, "command.update", "denied", principal=principal, resource_id=command_id, error_code=exc.code)
        raise
    _audit(request, "command.update", "success", principal=principal, resource_id=command_id)
    return service.command_view(updated)


@router.post("/internal/v1/commands/{command_id}/issue", summary="下达指令并创建个人分配")
def issue_command(
    command_id: str,
    payload: CommandIssue,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:issue")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    command = service.get_command(db, command_id)

    # 0. 幂等重放：同一个下达请求重试时返回原结果，不重复建分配
    dedupe_key = idempotency_key or getattr(request.state, "request_id", None)
    if (
        dedupe_key
        and command.last_request_id == dedupe_key
        and command.status != service.DRAFT
    ):
        return service.command_view(command)

    # 1. 冲突检查（同一依据报告 / 同一目标上的活动指令）
    conflicts_body = service.check_conflicts(
        db,
        source_report_id=command.source_report_id,
        objective=command.objective,
        exclude_command_id=command.id,
    )
    conflicts = conflicts_body["conflicts"]

    # 2. 执行员二次校验
    iam = getattr(request.app.state, "iam", None)
    if iam is not None:
        resolved = iam.resolve(
            payload.executor_ids,
            "executor",
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )
        invalid = [item["user_id"] for item in resolved if not item.get("valid")]
        if invalid:
            _audit(
                request,
                "command.issue",
                "denied",
                principal=principal,
                resource_id=command_id,
                error_code="INVALID_REQUEST",
                details={"invalid_executor_ids": invalid},
            )
            raise ApiError(
                "INVALID_REQUEST", "存在不可指派的执行员", details={"invalid_executor_ids": invalid}
            )

    # 3. 状态与冲突确认
    try:
        issuing = service.issue_command(
            db,
            command,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            conflict_acknowledged=payload.conflict_acknowledged,
            conflicts=conflicts,
            dedupe_key=dedupe_key,
        )
    except ApiError as exc:
        _audit(
            request,
            "command.issue",
            "denied",
            principal=principal,
            resource_id=command_id,
            error_code=exc.code,
            details=exc.details,
        )
        raise

    # 4. 调 Execution 建个人分配；失败进入补偿状态，绝不显示为已下达
    execution = getattr(request.app.state, "execution", None)
    if execution is None:
        service.mark_compensation(db, issuing, actor_id=principal.user_id, reason="execution 客户端未配置")
        raise ApiError("SERVICE_UNAVAILABLE", "执行服务客户端未配置")
    try:
        created = execution.create_assignments(
            {
                "command_id": issuing.id,
                "command_title": issuing.title,
                "command_content": issuing.content,
                "priority": issuing.priority,
                "deadline": issuing.deadline.isoformat() if issuing.deadline else None,
                "executor_ids": payload.executor_ids,
                "created_by": principal.user_id,
            },
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )
    except ApiError as exc:
        service.mark_compensation(
            db, issuing, actor_id=principal.user_id, reason=f"create_assignments:{exc.code}"
        )
        _audit(
            request,
            "command.issue",
            "failure",
            principal=principal,
            resource_id=command_id,
            error_code=exc.code,
            details={"failed_step": "create_assignments"},
        )
        raise ApiError("DEPENDENCY_FAILURE", "创建执行分配失败，指令未下达") from exc

    # 5. 写本地摘要并推进到 issued（唯一汇总入口）
    issued = service.attach_assignments(
        db, issuing, actor_id=principal.user_id, created=created
    )
    _audit(
        request,
        "command.issue",
        "success",
        principal=principal,
        resource_id=command_id,
        details={
            "executor_ids": payload.executor_ids,
            "assignments": len(issued.assignments),
            "status": issued.status,
            "conflicts_acknowledged": bool(conflicts),
        },
    )
    return service.command_view(issued)


@router.post("/internal/v1/commands/{command_id}/confirm-issue", summary="确认下达结果（协调器重试）")
def confirm_issue(
    command_id: str,
    payload: CommandConfirmIssue,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    command = service.get_command(db, command_id)
    if command.status == service.ISSUING:
        if not payload.assignments:
            raise ApiError("INVALID_REQUEST", "缺少个人分配列表")
        updated = service.attach_assignments(
            db, command, actor_id=principal.user_id, created=payload.assignments
        )
    elif command.status in {service.ISSUED, service.PARTIALLY_ACCEPTED, service.ACCEPTED, service.EXECUTING}:
        updated = command  # 幂等重试
    else:
        raise ApiError(
            "WORKFLOW_CONFLICT", "指令不在下达流程中", details={"status": command.status}
        )
    _audit(
        request,
        "command.confirm_issue",
        "success",
        principal=principal,
        resource_id=command_id,
        details={"status": updated.status},
    )
    return service.command_view(updated)


@router.post("/internal/v1/commands/{command_id}/cancel", summary="取消指令")
def cancel_command(
    command_id: str,
    payload: CommandCancel,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("command:issue")),
) -> dict:
    command = service.get_command(db, command_id)
    try:
        updated = service.cancel_command(
            db,
            command,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            reason=payload.reason,
        )
    except ApiError as exc:
        _audit(request, "command.cancel", "denied", principal=principal, resource_id=command_id, error_code=exc.code)
        raise
    _audit(
        request,
        "command.cancel",
        "success",
        principal=principal,
        resource_id=command_id,
        details={"reason": payload.reason},
    )
    return service.command_view(updated)


@router.post("/internal/v1/commands/{command_id}/assignment-state", summary="回写个人分配状态")
def apply_assignment_state(
    command_id: str,
    payload: AssignmentState,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    command = service.get_command(db, command_id)
    updated = service.apply_assignment_state(
        db,
        command,
        assignment_id=payload.assignment_id,
        executor_id=payload.executor_id,
        status=payload.status,
    )
    _audit(
        request,
        "command.status.recalculated",
        "success",
        principal=principal,
        resource_id=command_id,
        details={
            "assignment_id": payload.assignment_id,
            "assignment_status": payload.status,
            "command_status": updated.status,
        },
    )
    return service.command_view(updated)


@router.get("/internal/v1/commands/{command_id}/status", summary="指令总体状态")
def get_status(
    command_id: str,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    command = service.get_command(db, command_id)
    service.ensure_visible(command, principal.user_id)
    return service.status_view(command)
