"""执行业务规则：个人分配、状态流转与结果上报。

本服务**只拥有个人分配状态**，不计算指令总体状态（决策 D-01）：

- 每次状态流转后调用 decision-service 的 ``assignment-state`` 回写，由决策侧重算；
- ``/commands/{id}/summary`` 里的 ``aggregate_status`` 是从决策侧读来的，不是本地算的。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import ExecutionAssignment, ExecutionEvidence
from nis_shared.enums import AssignmentOutcome, AssignmentStatus
from nis_shared.errors import ApiError

PENDING = AssignmentStatus.PENDING.value
ACCEPTED = AssignmentStatus.ACCEPTED.value
EXECUTING = AssignmentStatus.EXECUTING.value
COMPLETED = AssignmentStatus.COMPLETED.value
FAILED = AssignmentStatus.FAILED.value
REJECTED = AssignmentStatus.REJECTED.value
CANCELLED = AssignmentStatus.CANCELLED.value


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"


# --------------------------------------------------------------------------- 视图


def evidence_view(item: ExecutionEvidence) -> dict[str, object]:
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


def assignment_view(item: ExecutionAssignment) -> dict[str, object]:
    view: dict[str, object] = {
        "id": item.id,
        "command_id": item.command_id,
        "command_title_snapshot": item.command_title_snapshot,
        "command_content_snapshot": item.command_content_snapshot,
        "priority": item.priority,
        "deadline": iso(item.deadline),
        "executor_id": item.executor_id,
        "status": item.status,
        "accepted_at": iso(item.accepted_at),
        "started_at": iso(item.started_at),
        "completed_at": iso(item.completed_at),
        "reject_reason": item.reject_reason,
        "version": item.version,
        "created_at": iso(item.created_at),
        "created_by": item.created_by,
        "updated_at": iso(item.updated_at),
        "updated_by": item.updated_by,
    }
    if item.result_outcome:
        view["result"] = {
            "outcome": item.result_outcome,
            "summary": item.result_summary,
            "detail": item.result_detail,
            "reported_at": iso(item.reported_at),
            "reported_by": item.reported_by,
            "evidence": [evidence_view(e) for e in item.evidence],
        }
    return view


# --------------------------------------------------------------------------- 查询与权限


def get_assignment(db: Session, assignment_id: str) -> ExecutionAssignment:
    item = db.scalars(
        select(ExecutionAssignment).where(ExecutionAssignment.id == assignment_id)
    ).one_or_none()
    if item is None:
        raise ApiError("RESOURCE_NOT_FOUND", "执行分配不存在")
    return item


def ensure_owner(item: ExecutionAssignment, user_id: str) -> None:
    """执行员只能看/操作分给自己的分配；他人分配按防泄露规则返回 404。"""

    if item.executor_id != user_id:
        raise ApiError("RESOURCE_NOT_FOUND", "执行分配不存在")


def list_assignments(
    db: Session, *, executor_id: str, status: str | None, page: int, page_size: int
) -> dict[str, object]:
    stmt = select(ExecutionAssignment).where(ExecutionAssignment.executor_id == executor_id)
    if status:
        stmt = stmt.where(ExecutionAssignment.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(ExecutionAssignment.updated_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [assignment_view(item) for item in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


# --------------------------------------------------------------------------- 创建（由决策服务调用）


def create_batch(
    db: Session,
    *,
    command_id: str,
    command_title: str,
    command_content: str | None,
    priority: str,
    deadline: datetime | None,
    executor_ids: list[str],
    created_by: str,
) -> list[ExecutionAssignment]:
    """批量建分配；同一 (command_id, executor_id) 幂等，重复调用只返回已存在的。"""

    existing = {
        item.executor_id: item
        for item in db.scalars(
            select(ExecutionAssignment).where(ExecutionAssignment.command_id == command_id)
        ).all()
    }
    created: list[ExecutionAssignment] = []
    for executor_id in dict.fromkeys(executor_ids):
        if executor_id in existing:
            created.append(existing[executor_id])
            continue
        item = ExecutionAssignment(
            command_id=command_id,
            command_title_snapshot=command_title,
            command_content_snapshot=command_content,
            priority=priority,
            deadline=deadline,
            executor_id=executor_id,
            status=PENDING,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(item)
        created.append(item)
    db.commit()
    for item in created:
        db.refresh(item)
    return created


# --------------------------------------------------------------------------- 状态流转


def _ensure_version(item: ExecutionAssignment, expected_version: int) -> None:
    if int(expected_version) != int(item.version):
        raise ApiError(
            "VERSION_CONFLICT",
            details={"expected": expected_version, "current": item.version},
        )


def accept(db: Session, item: ExecutionAssignment, *, actor_id: str, expected_version: int) -> ExecutionAssignment:
    if item.status == ACCEPTED:
        return item  # 幂等
    if item.status != PENDING:
        raise ApiError(
            "WORKFLOW_CONFLICT", "只有待接收的分配可以接收", details={"status": item.status}
        )
    _ensure_version(item, expected_version)
    item.status = ACCEPTED
    item.accepted_at = _now()
    item.version = int(item.version) + 1
    item.updated_by = actor_id
    item.updated_at = _now()
    db.commit()
    db.refresh(item)
    return item


def reject(
    db: Session,
    item: ExecutionAssignment,
    *,
    actor_id: str,
    expected_version: int,
    reason: str,
) -> ExecutionAssignment:
    if item.status == REJECTED:
        return item
    if item.status not in {PENDING, ACCEPTED}:
        raise ApiError(
            "WORKFLOW_CONFLICT", "当前状态不允许拒绝", details={"status": item.status}
        )
    _ensure_version(item, expected_version)
    item.status = REJECTED
    item.reject_reason = reason
    item.completed_at = _now()
    item.version = int(item.version) + 1
    item.updated_by = actor_id
    item.updated_at = _now()
    db.commit()
    db.refresh(item)
    return item


def start(db: Session, item: ExecutionAssignment, *, actor_id: str, expected_version: int) -> ExecutionAssignment:
    if item.status == EXECUTING:
        return item
    if item.status != ACCEPTED:
        raise ApiError(
            "WORKFLOW_CONFLICT", "只有已接收的分配可以开始执行", details={"status": item.status}
        )
    _ensure_version(item, expected_version)
    item.status = EXECUTING
    item.started_at = _now()
    item.version = int(item.version) + 1
    item.updated_by = actor_id
    item.updated_at = _now()
    db.commit()
    db.refresh(item)
    return item


def complete(
    db: Session,
    item: ExecutionAssignment,
    *,
    actor_id: str,
    expected_version: int,
    outcome: str,
    summary: str,
    detail: str | None,
    evidence: list[dict],
    idempotency_key: str | None,
) -> ExecutionAssignment:
    """提交结果；同一幂等键重放返回原结果，已完成后再提交返回 409。"""

    if (
        idempotency_key
        and item.idempotency_key == idempotency_key
        and item.status in {COMPLETED, FAILED}
    ):
        return item

    if item.status in {COMPLETED, FAILED}:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "该分配已有最终结果，不能重复提交",
            details={"status": item.status},
        )
    if item.status not in {ACCEPTED, EXECUTING}:
        raise ApiError(
            "WORKFLOW_CONFLICT", "当前状态不允许提交结果", details={"status": item.status}
        )
    _ensure_version(item, expected_version)

    item.status = COMPLETED if outcome != AssignmentOutcome.FAILURE.value else FAILED
    item.result_outcome = outcome
    item.result_summary = summary
    item.result_detail = detail
    item.reported_at = _now()
    item.reported_by = actor_id
    item.completed_at = _now()
    item.idempotency_key = idempotency_key
    item.version = int(item.version) + 1
    item.updated_by = actor_id
    item.updated_at = _now()

    for entry in evidence:
        db.add(
            ExecutionEvidence(
                assignment_id=item.id,
                file_name=entry["file_name"],
                media_type=entry["media_type"],
                size_bytes=int(entry.get("size_bytes") or 0),
                sha256=entry["sha256"],
                storage_ref=f"execution/{item.id}/{entry['file_name']}",
                uploaded_by=actor_id,
            )
        )
    db.commit()
    db.refresh(item)
    return item


def summary_items(db: Session, command_id: str) -> list[dict[str, object]]:
    rows = db.scalars(
        select(ExecutionAssignment)
        .where(ExecutionAssignment.command_id == command_id)
        .order_by(ExecutionAssignment.created_at)
    ).all()
    return [
        {
            "assignment_id": item.id,
            "executor_id": item.executor_id,
            "status": item.status,
            "outcome": item.result_outcome,
            "completed_at": iso(item.completed_at),
        }
        for item in rows
    ]
