"""分析服务路由（内部 /internal/v1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query, Request
from sqlalchemy.orm import Session

from app import service
from app.payloads import (
    ReportConfirmSubmission,
    ReportCreate,
    ReportDecisionState,
    ReportPatch,
    ReportSubmit,
)
from nis_shared.auth import Principal, get_principal, require_permission
from nis_shared.errors import ApiError
from nis_shared.pagination import PageQuery, page_query

router = APIRouter(tags=["分析报告"])


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
        resource_type="analysis_report",
        resource_id=resource_id,
        error_code=error_code,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def _assert_self(principal: Principal, claimed: str, field: str) -> None:
    if principal.user_id != claimed:
        raise ApiError("FORBIDDEN", "令牌主体与请求声明的用户不一致", details={"field": field})


def _snapshots_from_recon(
    request: Request, principal: Principal, record_ids: list[str]
) -> list[dict]:
    """用授权接口取回侦察数据并生成不可变快照；任何一条无权读取即整体拒绝。"""

    recon = getattr(request.app.state, "recon", None)
    if recon is None:
        raise ApiError("SERVICE_UNAVAILABLE", "侦察服务客户端未配置")

    snapshots: list[dict] = []
    for record_id in record_ids:
        view = recon.authorized_view(
            record_id,
            requester_id=principal.user_id,
            purpose="analysis",
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )
        record = view.get("record") or {}
        snapshots.append(
            {
                "recon_record_id": record_id,
                "recon_title_snapshot": record.get("title") or "（未提供标题）",
                "recon_owner_snapshot": record.get("owner_id"),
                "recon_priority_snapshot": record.get("priority"),
            }
        )
    return snapshots


@router.get("/internal/v1/analysis-reports", summary="查看本人或被指派的报告")
def list_reports(
    request: Request,
    viewer_user_id: str = Query(min_length=36, max_length=36),
    status: str | None = Query(default=None),
    recon_record_id: str | None = Query(default=None),
    page: PageQuery = Depends(page_query),
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("analysis:read_assigned")),
) -> dict:
    _assert_self(principal, viewer_user_id, "viewer_user_id")
    return service.list_reports(
        db,
        viewer_id=principal.user_id,
        status=status,
        recon_record_id=recon_record_id,
        page=page.page,
        page_size=page.page_size,
    )


@router.post("/internal/v1/analysis-reports", status_code=201, summary="创建分析报告")
def create_report(
    payload: ReportCreate,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("analysis:create")),
) -> dict:
    _assert_self(principal, payload.author_id, "author_id")
    if payload.organization_id != (principal.organization_id or payload.organization_id):
        raise ApiError("FORBIDDEN", "只能以本人所属组织创建报告")

    snapshots = _snapshots_from_recon(request, principal, payload.recon_record_ids)
    report = service.create_report(
        db,
        author_id=principal.user_id,
        organization_id=payload.organization_id,
        title=payload.title,
        recon_record_ids=payload.recon_record_ids,
        snapshots=snapshots,
        key_findings=payload.key_findings,
        relations=payload.relations,
        risk_level=payload.risk_level,
        recommended_actions=payload.recommended_actions,
        priority=payload.priority,
    )
    _audit(
        request,
        "analysis_report.create",
        "success",
        principal=principal,
        resource_id=report.id,
        details={"report_no": report.report_no, "recon_record_ids": payload.recon_record_ids},
    )
    return service.report_view(report)


@router.get("/internal/v1/analysis-reports/{report_id}", summary="报告详情")
def get_report(
    report_id: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("analysis:read_assigned")),
) -> dict:
    report = service.get_report(db, report_id)
    try:
        service.ensure_visible(report, principal.user_id)
    except ApiError:
        _audit(
            request,
            "analysis_report.read",
            "denied",
            principal=principal,
            resource_id=report_id,
            error_code="RESOURCE_NOT_FOUND",
        )
        raise
    return service.report_view(report)


@router.patch("/internal/v1/analysis-reports/{report_id}", summary="编辑报告草稿")
def update_report(
    report_id: str,
    payload: ReportPatch,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("analysis:edit_own_draft")),
) -> dict:
    report = service.get_report(db, report_id)
    try:
        updated = service.update_report(
            db,
            report,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            changes=payload.model_dump(exclude={"expected_version"}),
        )
    except ApiError as exc:
        _audit(
            request,
            "analysis_report.update",
            "denied",
            principal=principal,
            resource_id=report_id,
            error_code=exc.code,
            details=exc.details,
        )
        raise
    _audit(
        request, "analysis_report.update", "success", principal=principal, resource_id=report_id
    )
    return service.report_view(updated)


@router.post("/internal/v1/analysis-reports/{report_id}/submit", summary="提交报告并指派决策员")
def submit_report(
    report_id: str,
    payload: ReportSubmit,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission("analysis:submit")),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    report = service.get_report(db, report_id)

    iam = getattr(request.app.state, "iam", None)
    if iam is not None:
        resolved = iam.resolve(
            payload.decision_maker_ids,
            "decision_maker",
            token=principal.raw_token,
            request_id=getattr(request.state, "request_id", None),
        )
        invalid = [item["user_id"] for item in resolved if not item.get("valid")]
        if invalid:
            _audit(
                request,
                "analysis_report.submit",
                "denied",
                principal=principal,
                resource_id=report_id,
                error_code="INVALID_REQUEST",
                details={"invalid_decision_maker_ids": invalid},
            )
            raise ApiError(
                "INVALID_REQUEST",
                "存在不可指派的决策员",
                details={"invalid_decision_maker_ids": invalid},
            )

    dedupe_key = idempotency_key or getattr(request.state, "request_id", None)
    try:
        submitted = service.submit_report(
            db,
            report,
            actor_id=principal.user_id,
            expected_version=payload.expected_version,
            decision_maker_ids=payload.decision_maker_ids,
            ai_content_confirmed=payload.ai_content_confirmed,
            dedupe_key=dedupe_key,
        )
    except ApiError as exc:
        _audit(
            request,
            "analysis_report.submit",
            "denied",
            principal=principal,
            resource_id=report_id,
            error_code=exc.code,
            details=exc.details,
        )
        raise

    # 回写侦察记录的个人处理状态（失败不影响报告提交，但要留痕）
    recon = getattr(request.app.state, "recon", None)
    if recon is not None:
        for link in submitted.recon_links:
            try:
                recon.analysis_state(
                    link.recon_record_id,
                    analyst_id=principal.user_id,
                    assignment_status="completed",
                    reject_reason=None,
                    token=principal.raw_token,
                    request_id=getattr(request.state, "request_id", None),
                )
            except ApiError as exc:
                _audit(
                    request,
                    "recon_record.analysis_state",
                    "failure",
                    principal=principal,
                    resource_id=link.recon_record_id,
                    error_code=exc.code,
                    details={"reason": "state_writeback_failed"},
                )

    _audit(
        request,
        "analysis_report.submit",
        "success",
        principal=principal,
        resource_id=report_id,
        details={
            "decision_maker_ids": payload.decision_maker_ids,
            "status": submitted.status,
        },
    )
    return service.report_view(submitted)


@router.post(
    "/internal/v1/analysis-reports/{report_id}/confirm-submission", summary="确认提交（协调器重试）"
)
def confirm_submission(
    report_id: str,
    payload: ReportConfirmSubmission,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    report = service.get_report(db, report_id)
    updated = service.confirm_submission(
        db, report, actor_id=principal.user_id, expected_version=payload.expected_version
    )
    _audit(
        request,
        "analysis_report.confirm_submission",
        "success",
        principal=principal,
        resource_id=report_id,
        details={"status": updated.status},
    )
    return service.report_view(updated)


@router.post("/internal/v1/analysis-reports/{report_id}/decision-state", summary="回写决策状态")
def update_decision_state(
    report_id: str,
    payload: ReportDecisionState,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    report = service.get_report(db, report_id)
    updated = service.update_decision_state(
        db,
        report,
        actor_id=principal.user_id,
        state=payload.state,
        command_id=payload.command_id,
        reason=payload.reason,
    )
    _audit(
        request,
        "analysis_report.decision_state",
        "success",
        principal=principal,
        resource_id=report_id,
        details={"state": payload.state, "command_id": payload.command_id},
    )
    return service.report_view(updated)


@router.get("/internal/v1/analysis-reports/{report_id}/authorized-view", summary="跨服务授权读取")
def authorized_view(
    report_id: str,
    requester_user_id: str = Query(min_length=36, max_length=36),
    purpose: str = Query(pattern="^(decision|audit)$"),
    db: Session = Depends(get_db),
    principal: Principal = Depends(get_principal),
) -> dict:
    _assert_self(principal, requester_user_id, "requester_user_id")
    report = service.get_report(db, report_id)
    return service.authorized_view(db, report, requester_id=principal.user_id, purpose=purpose)
