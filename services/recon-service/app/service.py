"""侦察业务规则：草稿、编辑、提交、指派与授权读取。

状态机（docs/workflow.md 第 2 节）：

    draft --提交--> submitting --全部指派成功--> assigned
                                  \\--持续失败--> compensation_required

本期把「校验候选 + 建指派」放在一个本地事务里完成（提交即 assigned），
``confirm-submission`` 作为协调器重试入口保持幂等；跨服务失败时用
``mark-compensation`` 落 ``compensation_required``，绝不显示为已提交。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ReconAssignment, ReconEvidence, ReconRecord
from nis_shared.enums import Priority, ReconStatus, TargetHandlerStatus
from nis_shared.errors import ApiError

DRAFT = ReconStatus.DRAFT.value
SUBMITTING = ReconStatus.SUBMITTING.value
ASSIGNED = ReconStatus.ASSIGNED.value
COMPENSATION = ReconStatus.COMPENSATION_REQUIRED.value
EDITABLE_STATUSES = {DRAFT}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"


def next_record_no(db: Session) -> str:
    """``REC-YYYYMMDD-NNNN``：展示用编号，不替代 UUID（数据模型 1.2）。"""

    today = _now().strftime("%Y%m%d")
    prefix = f"REC-{today}-"
    used = db.scalar(
        select(func.count()).select_from(ReconRecord).where(ReconRecord.record_no.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{used + 1:04d}"


# --------------------------------------------------------------------------- 视图


def assignment_view(item: ReconAssignment) -> dict[str, object]:
    return {
        "id": item.id,
        "record_id": item.record_id,
        "analyst_id": item.analyst_id,
        "status": item.status,
        "assigned_by": item.assigned_by,
        "assigned_at": iso(item.assigned_at),
        "responded_at": iso(item.responded_at),
        "reject_reason": item.reject_reason,
    }


def evidence_view(item: ReconEvidence) -> dict[str, object]:
    return {
        "id": item.id,
        "file_name": item.file_name,
        "media_type": item.media_type,
        "size_bytes": item.size_bytes,
        "sha256": item.sha256,
        "storage_ref": item.storage_ref,
        "created_at": iso(item.created_at),
        "created_by": item.uploaded_by,
    }


def record_view(
    record: ReconRecord,
    *,
    include_assignments: bool = True,
    include_evidence: bool = True,
) -> dict[str, object]:
    view: dict[str, object] = {
        "id": record.id,
        "record_no": record.record_no,
        "title": record.title,
        "source_type": record.source_type,
        "source_ref": record.source_ref,
        "content": record.content,
        "status": record.status,
        "credibility": record.credibility,
        "priority": record.priority,
        "owner_id": record.owner_id,
        "organization_id": record.organization_id,
        "submitted_at": iso(record.submitted_at),
        "version": record.version,
        "created_at": iso(record.created_at),
        "created_by": record.created_by,
        "updated_at": iso(record.updated_at),
        "updated_by": record.updated_by,
    }
    if include_assignments:
        view["assignments"] = [assignment_view(item) for item in record.assignments]
    if include_evidence:
        view["evidence"] = [evidence_view(item) for item in record.evidence]
    return view


def summary_view(record: ReconRecord) -> dict[str, object]:
    """``scope=summary_only``：只给标题、可信度、优先级与来源类型。"""

    return {
        "id": record.id,
        "record_no": record.record_no,
        "title": record.title,
        "source_type": record.source_type,
        "credibility": record.credibility,
        "priority": record.priority,
        "status": record.status,
        "owner_id": record.owner_id,
        "organization_id": record.organization_id,
        "version": record.version,
    }


# --------------------------------------------------------------------------- 查询与权限


def get_record(db: Session, record_id: str) -> ReconRecord:
    record = db.scalars(select(ReconRecord).where(ReconRecord.id == record_id)).one_or_none()
    if record is None:
        raise ApiError("RESOURCE_NOT_FOUND", "侦察记录不存在")
    return record


def is_owner(record: ReconRecord, user_id: str) -> bool:
    return record.owner_id == user_id


def is_assigned(record: ReconRecord, user_id: str) -> bool:
    return any(item.analyst_id == user_id and item.status != TargetHandlerStatus.REJECTED.value
               for item in record.assignments)


def ensure_visible(record: ReconRecord, viewer_id: str) -> None:
    """本人或被指派的记录才可见；其余按防泄露规则返回 404。"""

    if is_owner(record, viewer_id) or is_assigned(record, viewer_id):
        return
    raise ApiError("RESOURCE_NOT_FOUND", "侦察记录不存在")


def ensure_owner(record: ReconRecord, user_id: str) -> None:
    if not is_owner(record, user_id):
        raise ApiError("FORBIDDEN", "只有记录创建者可以执行该操作")


def list_records(
    db: Session, *, viewer_id: str, status: str | None, page: int, page_size: int
) -> dict[str, object]:
    owned = select(ReconRecord.owner_id).where(ReconRecord.owner_id == viewer_id)
    assigned = (
        select(ReconAssignment.record_id)
        .where(ReconAssignment.analyst_id == viewer_id)
        .where(ReconAssignment.status != TargetHandlerStatus.REJECTED.value)
    )
    stmt = select(ReconRecord).where(
        (ReconRecord.owner_id.in_(owned)) | (ReconRecord.id.in_(assigned))
    )
    if status:
        stmt = stmt.where(ReconRecord.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ReconRecord.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [record_view(item) for item in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


# --------------------------------------------------------------------------- 写入


def create_record(
    db: Session,
    *,
    owner_id: str,
    organization_id: str,
    title: str,
    source_type: str,
    source_ref: str | None,
    content: str,
    credibility: str,
    priority: str,
    evidence: list[dict] | None = None,
) -> ReconRecord:
    record = ReconRecord(
        record_no=next_record_no(db),
        title=title,
        source_type=source_type,
        source_ref=source_ref,
        content=content,
        credibility=credibility,
        priority=priority,
        status=DRAFT,
        owner_id=owner_id,
        organization_id=organization_id,
        created_by=owner_id,
        updated_by=owner_id,
    )
    db.add(record)
    db.flush()
    for item in evidence or []:
        db.add(
            ReconEvidence(
                record_id=record.id,
                file_name=item["file_name"],
                media_type=item["media_type"],
                size_bytes=int(item.get("size_bytes") or 0),
                sha256=item["sha256"],
                storage_ref=f"recon/{record.id}/{item['file_name']}",
                uploaded_by=owner_id,
            )
        )
    db.commit()
    db.refresh(record)
    return record


def update_record(
    db: Session,
    record: ReconRecord,
    *,
    actor_id: str,
    expected_version: int,
    changes: dict[str, object],
) -> ReconRecord:
    ensure_owner(record, actor_id)
    if record.status not in EDITABLE_STATUSES:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "只有草稿可以编辑，提交后请使用退回或新版本流程",
            details={"status": record.status},
        )
    if int(expected_version) != int(record.version):
        raise ApiError(
            "VERSION_CONFLICT",
            details={"expected": expected_version, "current": record.version},
        )
    for field, value in changes.items():
        if value is not None and field != "expected_version":
            setattr(record, field, value)
    record.version = int(record.version) + 1
    record.updated_by = actor_id
    record.updated_at = _now()
    db.commit()
    db.refresh(record)
    return record


def submit_record(
    db: Session,
    record: ReconRecord,
    *,
    actor_id: str,
    expected_version: int,
    analyst_ids: list[str],
    priority: str | None,
    dedupe_key: str | None,
) -> ReconRecord:
    """校验并提交：必填完整、候选合法、幂等重试返回原结果。"""

    ensure_owner(record, actor_id)

    # 幂等：同一提交键重放时返回当前状态，不重复建指派
    if (
        dedupe_key
        and record.last_request_id == dedupe_key
        and record.status in {SUBMITTING, ASSIGNED}
    ):
        return record

    if record.status not in EDITABLE_STATUSES:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "当前状态不允许提交",
            details={"status": record.status},
        )
    if int(expected_version) != int(record.version):
        raise ApiError(
            "VERSION_CONFLICT",
            details={"expected": expected_version, "current": record.version},
        )
    if not record.title or not record.content:
        raise ApiError("INVALID_REQUEST", "标题与正文不能为空")

    wanted = list(dict.fromkeys(analyst_ids))
    existing = {item.analyst_id for item in record.assignments}
    new_ids = [item for item in wanted if item not in existing]

    record.status = SUBMITTING
    record.submitted_at = _now()
    record.last_request_id = dedupe_key
    record.updated_by = actor_id
    db.flush()

    for analyst_id in new_ids:
        db.add(
            ReconAssignment(
                record_id=record.id,
                analyst_id=analyst_id,
                status=TargetHandlerStatus.PENDING.value,
                assigned_by=actor_id,
                assigned_at=_now(),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

    if priority:
        record.priority = priority
    record.status = ASSIGNED
    record.version = int(record.version) + 1
    record.updated_at = _now()
    db.commit()
    db.refresh(record)
    return record


def confirm_submission(
    db: Session, record: ReconRecord, *, actor_id: str, expected_version: int
) -> ReconRecord:
    """协调器重试入口：已 assigned 直接返回；submitting 且有指派则推进到 assigned。"""

    if record.status == ASSIGNED:
        return record
    if record.status != SUBMITTING:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "只有提交中的记录可以确认",
            details={"status": record.status},
        )
    if int(expected_version) != int(record.version):
        raise ApiError(
            "VERSION_CONFLICT", details={"expected": expected_version, "current": record.version}
        )
    if not record.assignments:
        raise ApiError("INVALID_REQUEST", "没有可确认的分析员指派")
    record.status = ASSIGNED
    record.version = int(record.version) + 1
    record.updated_by = actor_id
    record.updated_at = _now()
    db.commit()
    db.refresh(record)
    return record


def mark_compensation(
    db: Session, record: ReconRecord, *, reason: str | None, failed_step: str
) -> ReconRecord:
    record.status = COMPENSATION
    record.updated_at = _now()
    record.updated_by = record.updated_by or record.owner_id
    db.commit()
    db.refresh(record)
    return record


def update_analysis_state(
    db: Session,
    record: ReconRecord,
    *,
    analyst_id: str,
    assignment_status: str,
    reject_reason: str | None,
) -> ReconRecord:
    """分析员侧回写个人处理状态；记录级状态按「全部完成才 analyzed」汇总。"""

    assignment = next(
        (item for item in record.assignments if item.analyst_id == analyst_id), None
    )
    if assignment is None:
        raise ApiError("RESOURCE_NOT_FOUND", "该分析员没有被指派到这条记录")
    if assignment_status == TargetHandlerStatus.REJECTED.value and not reject_reason:
        raise ApiError("INVALID_REQUEST", "拒绝处理必须填写理由")

    assignment.status = assignment_status
    assignment.responded_at = _now()
    assignment.reject_reason = reject_reason
    assignment.updated_by = analyst_id
    assignment.updated_at = _now()

    statuses = {item.status for item in record.assignments}
    if statuses and statuses <= {TargetHandlerStatus.COMPLETED.value}:
        record.status = ReconStatus.ANALYZED.value
    elif TargetHandlerStatus.IN_PROGRESS.value in statuses:
        record.status = ReconStatus.UNDER_ANALYSIS.value
    record.updated_at = _now()
    db.commit()
    db.refresh(record)
    return record


def authorized_view(
    db: Session, record: ReconRecord, *, requester_id: str, purpose: str
) -> dict[str, object]:
    """跨服务授权读取：分析员拿全文，决策员/审计按摘要。"""

    if purpose == "analysis":
        if not is_assigned(record, requester_id):
            raise ApiError("FORBIDDEN", "只有当被指派的分析员可以读取全文")
        return {
            "record_id": record.id,
            "granted": True,
            "scope": "full",
            "record": record_view(record),
        }
    if purpose == "decision":
        # 决策员经报告间接读取：只在记录已有分析产出时给摘要
        if record.status not in {ReconStatus.ANALYZED.value, ASSIGNED, ReconStatus.UNDER_ANALYSIS.value}:
            raise ApiError("FORBIDDEN", "该记录尚无分析产出")
        return {
            "record_id": record.id,
            "granted": True,
            "scope": "summary_only",
            "record": summary_view(record),
        }
    if purpose == "audit":
        return {
            "record_id": record.id,
            "granted": True,
            "scope": "summary_only",
            "record": summary_view(record),
        }
    raise ApiError("INVALID_REQUEST", "未知的读取用途", details={"purpose": purpose})


def default_priority(value: str | None) -> str:
    return value or Priority.NORMAL.value
