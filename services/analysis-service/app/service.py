"""分析业务规则：报告草稿、引用快照、提交与决策员指派。

状态机（docs/workflow.md 第 3 节）：``draft -> submitting -> assigned -> under_decision -> decided``。

多分析员并存：报告是独立资源，同一侦察记录可以有多份报告，谁都不能覆盖别人；
决策员按作者、时间与证据并列比较（需求 FR-ANALYSIS-005）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnalysisReport, ReportAssignment, ReportReconLink
from nis_shared.enums import ReportStatus, TargetHandlerStatus
from nis_shared.errors import ApiError

DRAFT = ReportStatus.DRAFT.value
SUBMITTING = ReportStatus.SUBMITTING.value
ASSIGNED = ReportStatus.ASSIGNED.value
UNDER_DECISION = ReportStatus.UNDER_DECISION.value
DECIDED = ReportStatus.DECIDED.value
REJECTED = ReportStatus.REJECTED.value
COMPENSATION = ReportStatus.COMPENSATION_REQUIRED.value
EDITABLE_STATUSES = {DRAFT}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"


def next_report_no(db: Session) -> str:
    today = _now().strftime("%Y%m%d")
    prefix = f"RPT-{today}-"
    used = db.scalar(
        select(func.count())
        .select_from(AnalysisReport)
        .where(AnalysisReport.report_no.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{used + 1:04d}"


# --------------------------------------------------------------------------- 视图


def link_view(link: ReportReconLink) -> dict[str, object]:
    return {
        "recon_record_id": link.recon_record_id,
        "recon_title_snapshot": link.recon_title_snapshot,
        "recon_owner_snapshot": link.recon_owner_snapshot,
        "recon_priority_snapshot": link.recon_priority_snapshot,
        "linked_at": iso(link.linked_at),
    }


def report_view(report: AnalysisReport) -> dict[str, object]:
    return {
        "id": report.id,
        "report_no": report.report_no,
        "title": report.title,
        "status": report.status,
        "author_id": report.author_id,
        "organization_id": report.organization_id,
        "recon_links": [link_view(link) for link in report.recon_links],
        "key_findings": report.key_findings,
        "relations": report.relations,
        "risk_level": report.risk_level,
        "recommended_actions": report.recommended_actions,
        "priority": report.priority,
        "ai_content_confirmed": bool(report.ai_content_confirmed),
        "human_confirmed": bool(report.human_confirmed),
        "confirmed_by": report.confirmed_by,
        "confirmed_at": iso(report.confirmed_at),
        "decision_maker_ids": [item.decision_maker_id for item in report.assignments],
        "submitted_at": iso(report.submitted_at),
        "version": report.version,
        "created_at": iso(report.created_at),
        "created_by": report.created_by,
        "updated_at": iso(report.updated_at),
        "updated_by": report.updated_by,
    }


# --------------------------------------------------------------------------- 查询与权限


def get_report(db: Session, report_id: str) -> AnalysisReport:
    report = db.scalars(select(AnalysisReport).where(AnalysisReport.id == report_id)).one_or_none()
    if report is None:
        raise ApiError("RESOURCE_NOT_FOUND", "分析报告不存在")
    return report


def is_author(report: AnalysisReport, user_id: str) -> bool:
    return report.author_id == user_id


def is_assigned(report: AnalysisReport, user_id: str) -> bool:
    return any(
        item.decision_maker_id == user_id and item.status != TargetHandlerStatus.REJECTED.value
        for item in report.assignments
    )


def ensure_visible(report: AnalysisReport, viewer_id: str) -> None:
    if is_author(report, viewer_id) or is_assigned(report, viewer_id):
        return
    raise ApiError("RESOURCE_NOT_FOUND", "分析报告不存在")


def list_reports(
    db: Session,
    *,
    viewer_id: str,
    status: str | None,
    recon_record_id: str | None,
    page: int,
    page_size: int,
) -> dict[str, object]:
    assigned = (
        select(ReportAssignment.report_id)
        .where(ReportAssignment.decision_maker_id == viewer_id)
        .where(ReportAssignment.status != TargetHandlerStatus.REJECTED.value)
    )
    stmt = select(AnalysisReport).where(
        (AnalysisReport.author_id == viewer_id) | (AnalysisReport.id.in_(assigned))
    )
    if status:
        stmt = stmt.where(AnalysisReport.status == status)
    if recon_record_id:
        stmt = stmt.join(ReportReconLink, ReportReconLink.report_id == AnalysisReport.id).where(
            ReportReconLink.recon_record_id == recon_record_id
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AnalysisReport.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [report_view(item) for item in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


# --------------------------------------------------------------------------- 写入


def create_report(
    db: Session,
    *,
    author_id: str,
    organization_id: str,
    title: str,
    recon_record_ids: list[str],
    snapshots: list[dict] | None,
    key_findings: str,
    relations: str | None,
    risk_level: str,
    recommended_actions: str,
    priority: str,
) -> AnalysisReport:
    snapshots = snapshots or []
    snapshot_by_id = {item["recon_record_id"]: item for item in snapshots}
    report = AnalysisReport(
        report_no=next_report_no(db),
        title=title,
        status=DRAFT,
        author_id=author_id,
        organization_id=organization_id,
        key_findings=key_findings,
        relations=relations,
        risk_level=risk_level,
        recommended_actions=recommended_actions,
        priority=priority,
        created_by=author_id,
        updated_by=author_id,
    )
    db.add(report)
    db.flush()

    for record_id in dict.fromkeys(recon_record_ids):
        snapshot = snapshot_by_id.get(record_id) or {}
        db.add(
            ReportReconLink(
                report_id=report.id,
                recon_record_id=record_id,
                recon_title_snapshot=str(snapshot.get("recon_title_snapshot") or "（未提供快照）"),
                recon_owner_snapshot=snapshot.get("recon_owner_snapshot"),
                recon_priority_snapshot=snapshot.get("recon_priority_snapshot"),
                linked_at=_now(),
                created_by=author_id,
                updated_by=author_id,
            )
        )
    db.commit()
    db.refresh(report)
    return report


def update_report(
    db: Session,
    report: AnalysisReport,
    *,
    actor_id: str,
    expected_version: int,
    changes: dict[str, object],
) -> AnalysisReport:
    if not is_author(report, actor_id):
        raise ApiError("FORBIDDEN", "只有报告作者可以编辑")
    if report.status not in EDITABLE_STATUSES:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "只有草稿可以编辑，提交后请使用退回流程",
            details={"status": report.status},
        )
    if int(expected_version) != int(report.version):
        raise ApiError(
            "VERSION_CONFLICT", details={"expected": expected_version, "current": report.version}
        )
    for field, value in changes.items():
        if value is not None and field != "expected_version":
            setattr(report, field, value)
    report.version = int(report.version) + 1
    report.updated_by = actor_id
    report.updated_at = _now()
    db.commit()
    db.refresh(report)
    return report


def submit_report(
    db: Session,
    report: AnalysisReport,
    *,
    actor_id: str,
    expected_version: int,
    decision_maker_ids: list[str],
    ai_content_confirmed: bool,
    dedupe_key: str | None,
) -> AnalysisReport:
    if not is_author(report, actor_id):
        raise ApiError("FORBIDDEN", "只有报告作者可以提交")

    if (
        dedupe_key
        and report.last_request_id == dedupe_key
        and report.status in {SUBMITTING, ASSIGNED}
    ):
        return report

    if report.status not in EDITABLE_STATUSES:
        raise ApiError(
            "WORKFLOW_CONFLICT", "当前状态不允许提交", details={"status": report.status}
        )
    if int(expected_version) != int(report.version):
        raise ApiError(
            "VERSION_CONFLICT", details={"expected": expected_version, "current": report.version}
        )
    if not ai_content_confirmed:
        raise ApiError("INVALID_REQUEST", "必须先逐条确认或舍弃 AI 建议内容")
    if not report.recon_links:
        raise ApiError("INVALID_REQUEST", "报告至少关联一条侦察记录")

    wanted = list(dict.fromkeys(decision_maker_ids))
    existing = {item.decision_maker_id for item in report.assignments}

    report.status = SUBMITTING
    report.ai_content_confirmed = True
    report.human_confirmed = True
    report.confirmed_by = actor_id
    report.confirmed_at = _now()
    report.submitted_at = _now()
    report.last_request_id = dedupe_key
    report.updated_by = actor_id
    db.flush()

    for user_id in wanted:
        if user_id in existing:
            continue
        db.add(
            ReportAssignment(
                report_id=report.id,
                decision_maker_id=user_id,
                status=TargetHandlerStatus.PENDING.value,
                assigned_by=actor_id,
                assigned_at=_now(),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
    report.status = ASSIGNED
    report.version = int(report.version) + 1
    report.updated_at = _now()
    db.commit()
    db.refresh(report)
    return report


def confirm_submission(
    db: Session, report: AnalysisReport, *, actor_id: str, expected_version: int
) -> AnalysisReport:
    if report.status in {ASSIGNED, UNDER_DECISION, DECIDED}:
        return report
    if report.status != SUBMITTING:
        raise ApiError(
            "WORKFLOW_CONFLICT", "只有提交中的报告可以确认", details={"status": report.status}
        )
    if int(expected_version) != int(report.version):
        raise ApiError(
            "VERSION_CONFLICT", details={"expected": expected_version, "current": report.version}
        )
    if not report.assignments:
        raise ApiError("INVALID_REQUEST", "没有可确认的决策员指派")
    report.status = ASSIGNED
    report.version = int(report.version) + 1
    report.updated_by = actor_id
    report.updated_at = _now()
    db.commit()
    db.refresh(report)
    return report


def update_decision_state(
    db: Session,
    report: AnalysisReport,
    *,
    actor_id: str,
    state: str,
    command_id: str | None,
    reason: str | None,
) -> AnalysisReport:
    """决策员侧回写：开始决策、已决策（关联指令）或退回。"""

    if not is_assigned(report, actor_id):
        raise ApiError("FORBIDDEN", "只有当被指派的决策员可以更新报告状态")
    if report.status in {DRAFT, SUBMITTING}:
        raise ApiError(
            "WORKFLOW_CONFLICT", "报告尚未提交", details={"status": report.status}
        )
    if state == "under_decision":
        report.status = UNDER_DECISION
    elif state == "decided":
        if not command_id:
            raise ApiError("INVALID_REQUEST", "标记已决策必须提供指令 ID")
        report.status = DECIDED
    elif state == "rejected":
        if not reason:
            raise ApiError("INVALID_REQUEST", "退回必须填写理由")
        report.status = REJECTED
    else:  # pragma: no cover - 由请求模型约束
        raise ApiError("INVALID_REQUEST", "未知的决策状态")

    for item in report.assignments:
        if item.decision_maker_id == actor_id:
            item.status = (
                TargetHandlerStatus.REJECTED.value
                if state == "rejected"
                else TargetHandlerStatus.COMPLETED.value
            )
            item.responded_at = _now()
            item.reject_reason = reason if state == "rejected" else None
            item.updated_by = actor_id

    report.updated_by = actor_id
    report.updated_at = _now()
    report.version = int(report.version) + 1
    db.commit()
    db.refresh(report)
    return report


def mark_compensation(db: Session, report: AnalysisReport, *, reason: str | None) -> AnalysisReport:
    report.status = COMPENSATION
    report.updated_at = _now()
    db.commit()
    db.refresh(report)
    return report


def authorized_view(
    db: Session, report: AnalysisReport, *, requester_id: str, purpose: str
) -> dict[str, object]:
    """决策员读取被指派报告；审计只读；其他人一律不可见。"""

    if purpose == "decision":
        if not is_assigned(report, requester_id):
            raise ApiError("FORBIDDEN", "只有当被指派的决策员可以读取该报告")
    elif purpose == "audit":
        pass
    else:
        raise ApiError("INVALID_REQUEST", "未知的读取用途", details={"purpose": purpose})
    return {"report_id": report.id, "granted": True, "report": report_view(report)}
