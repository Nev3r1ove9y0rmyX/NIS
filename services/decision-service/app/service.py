"""决策业务规则：指令草稿、冲突检查、下达、取消与总体状态汇总。

**总体状态只有一个计算入口**（决策 D-01，docs/workflow.md 第 5.1 节）：

- ``commands.status`` 只由本服务 :func:`recompute_status` 重算；
- 重算时机只有两个：``confirm-issue``（全部个人分配建成）与每次 ``assignment-state`` 回写；
- Execution 侧只回写个人分配状态，不算总体状态；
- ``command_assignments.status`` 是个人状态的摘要副本，不是事实来源。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Command, CommandAssignment, CommandConflictCheck
from nis_shared.enums import AssignmentStatus, CommandStatus
from nis_shared.errors import ApiError

DRAFT = CommandStatus.DRAFT.value
ISSUING = CommandStatus.ISSUING.value
ISSUED = CommandStatus.ISSUED.value
PARTIALLY_ACCEPTED = CommandStatus.PARTIALLY_ACCEPTED.value
ACCEPTED = CommandStatus.ACCEPTED.value
EXECUTING = CommandStatus.EXECUTING.value
PARTIALLY_COMPLETED = CommandStatus.PARTIALLY_COMPLETED.value
COMPLETED = CommandStatus.COMPLETED.value
FAILED = CommandStatus.FAILED.value
REJECTED = CommandStatus.REJECTED.value
CANCELLED = CommandStatus.CANCELLED.value
COMPENSATION = CommandStatus.COMPENSATION_REQUIRED.value
EDITABLE_STATUSES = {DRAFT}

#: 仍占用目标的「活动指令」状态：冲突检查只跟这些比较。
ACTIVE_STATUSES = {
    DRAFT,
    ISSUING,
    ISSUED,
    PARTIALLY_ACCEPTED,
    ACCEPTED,
    EXECUTING,
    PARTIALLY_COMPLETED,
}
#: 可以取消的指令状态：已有完成结果的不能取消。
CANCELLABLE_STATUSES = {
    ISSUED,
    PARTIALLY_ACCEPTED,
    ACCEPTED,
    EXECUTING,
    PARTIALLY_COMPLETED,
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"


def next_command_no(db: Session) -> str:
    today = _now().strftime("%Y%m%d")
    prefix = f"CMD-{today}-"
    used = db.scalar(
        select(func.count()).select_from(Command).where(Command.command_no.like(f"{prefix}%"))
    ) or 0
    return f"{prefix}{used + 1:04d}"


# --------------------------------------------------------------------------- 视图


def assignment_summary_view(item: CommandAssignment) -> dict[str, object]:
    return {
        "assignment_id": item.assignment_id,
        "executor_id": item.executor_id,
        "status": item.status,
        "updated_at": iso(item.updated_at),
    }


def command_view(command: Command) -> dict[str, object]:
    return {
        "id": command.id,
        "command_no": command.command_no,
        "title": command.title,
        "objective": command.objective,
        "content": command.content,
        "status": command.status,
        "priority": command.priority,
        "deadline": iso(command.deadline),
        "decision_maker_id": command.decision_maker_id,
        "organization_id": command.organization_id,
        "source_report_id": command.source_report_id,
        "assignments": [assignment_summary_view(item) for item in command.assignments],
        "issued_at": iso(command.issued_at),
        "cancelled_at": iso(command.cancelled_at),
        "cancel_reason": command.cancel_reason,
        "version": command.version,
        "created_at": iso(command.created_at),
        "created_by": command.created_by,
        "updated_at": iso(command.updated_at),
        "updated_by": command.updated_by,
    }


# --------------------------------------------------------------------------- 汇总（唯一入口）


def recompute_status(assignments: list[CommandAssignment]) -> str:
    """把个人分配状态汇总成指令总体状态（docs/workflow.md 第 5 节）。

    规则顺序固定，禁止在别处重复实现：

    1. 全部 ``pending`` → ``issued``
    2. 有 ``executing`` → ``executing``
    3. 部分完成且仍有活动分配 → ``partially_completed``
    4. 全部有效分配完成 → ``completed``
    5. 全部失败/拒绝且无成功 → ``failed`` / ``rejected``
    6. 部分接收、仍有待处理 → ``partially_accepted``
    7. 全部未拒绝的分配已接收 → ``accepted``
    """

    if not assignments:
        return ISSUING

    statuses = [item.status for item in assignments]
    usable = [s for s in statuses if s != AssignmentStatus.CANCELLED.value]
    if not usable:
        return CANCELLED

    done = {AssignmentStatus.COMPLETED.value}
    failed = {AssignmentStatus.FAILED.value}
    rejected = {AssignmentStatus.REJECTED.value}

    if all(s == AssignmentStatus.PENDING.value for s in usable):
        return ISSUED
    if any(s == AssignmentStatus.EXECUTING.value for s in usable):
        return EXECUTING
    if done & set(usable) and not set(usable) <= done:
        return PARTIALLY_COMPLETED
    if set(usable) <= done:
        return COMPLETED
    if set(usable) <= (failed | rejected):
        return REJECTED if set(usable) <= rejected else FAILED
    accepted = {AssignmentStatus.ACCEPTED.value}
    if set(usable) <= (accepted | done):
        return ACCEPTED
    if accepted & set(usable):
        return PARTIALLY_ACCEPTED
    return PARTIALLY_ACCEPTED if rejected & set(usable) else ISSUED


# --------------------------------------------------------------------------- 查询与权限


def get_command(db: Session, command_id: str) -> Command:
    command = db.scalars(select(Command).where(Command.id == command_id)).one_or_none()
    if command is None:
        raise ApiError("RESOURCE_NOT_FOUND", "指令不存在")
    return command


def is_owner(command: Command, user_id: str) -> bool:
    return command.decision_maker_id == user_id


def is_assigned(command: Command, user_id: str) -> bool:
    return any(item.executor_id == user_id for item in command.assignments)


def ensure_visible(command: Command, viewer_id: str) -> None:
    if is_owner(command, viewer_id) or is_assigned(command, viewer_id):
        return
    raise ApiError("RESOURCE_NOT_FOUND", "指令不存在")


def list_commands(
    db: Session, *, viewer_id: str, status: str | None, page: int, page_size: int
) -> dict[str, object]:
    assigned = select(CommandAssignment.command_id).where(
        CommandAssignment.executor_id == viewer_id
    )
    stmt = select(Command).where(
        or_(Command.decision_maker_id == viewer_id, Command.id.in_(assigned))
    )
    if status:
        stmt = stmt.where(Command.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Command.updated_at.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [command_view(item) for item in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


# --------------------------------------------------------------------------- 写入


def create_command(
    db: Session,
    *,
    decision_maker_id: str,
    organization_id: str,
    title: str,
    objective: str,
    content: str,
    priority: str,
    deadline: datetime | None,
    source_report_id: str,
) -> Command:
    command = Command(
        command_no=next_command_no(db),
        title=title,
        objective=objective,
        content=content,
        priority=priority,
        deadline=deadline,
        status=DRAFT,
        decision_maker_id=decision_maker_id,
        organization_id=organization_id,
        source_report_id=source_report_id,
        created_by=decision_maker_id,
        updated_by=decision_maker_id,
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return command


def update_command(
    db: Session, command: Command, *, actor_id: str, expected_version: int, changes: dict
) -> Command:
    if not is_owner(command, actor_id):
        raise ApiError("FORBIDDEN", "只有指令创建者可以编辑")
    if command.status not in EDITABLE_STATUSES:
        raise ApiError(
            "WORKFLOW_CONFLICT", "只有草稿可以编辑", details={"status": command.status}
        )
    if int(expected_version) != int(command.version):
        raise ApiError(
            "VERSION_CONFLICT",
            details={"expected": expected_version, "current": command.version},
        )
    for field, value in changes.items():
        if value is not None and field != "expected_version":
            setattr(command, field, value)
    command.version = int(command.version) + 1
    command.updated_by = actor_id
    command.updated_at = _now()
    db.commit()
    db.refresh(command)
    return command


def check_conflicts(
    db: Session,
    *,
    source_report_id: str,
    objective: str | None,
    exclude_command_id: str | None,
) -> dict[str, object]:
    """同一依据报告或同一目标上的活动指令视为潜在冲突。"""

    stmt = select(Command).where(Command.status.in_(ACTIVE_STATUSES))
    if exclude_command_id:
        stmt = stmt.where(Command.id != exclude_command_id)
    conditions = [Command.source_report_id == source_report_id]
    if objective:
        conditions.append(Command.objective == objective)
    stmt = stmt.where(or_(*conditions))

    rows = db.scalars(stmt.order_by(Command.updated_at.desc())).all()
    conflicts = [
        {
            "command_id": item.id,
            "command_no": item.command_no,
            "status": item.status,
            "reason": "same_source_report"
            if item.source_report_id == source_report_id
            else "same_objective",
        }
        for item in rows
    ]
    return {"has_conflict": bool(conflicts), "conflicts": conflicts}


def record_conflict_check(
    db: Session,
    command: Command,
    *,
    checked_by: str,
    conflicts: list[dict],
    decision: str,
    reason: str | None = None,
) -> CommandConflictCheck:
    row = CommandConflictCheck(
        command_id=command.id,
        checked_at=_now(),
        checked_by=checked_by,
        conflict_type="same_source_report_or_objective",
        matched_command_ids=[item["command_id"] for item in conflicts],
        decision=decision,
        reason=reason,
        created_by=checked_by,
        updated_by=checked_by,
    )
    db.add(row)
    db.flush()
    return row


def issue_command(
    db: Session,
    command: Command,
    *,
    actor_id: str,
    expected_version: int,
    conflict_acknowledged: bool,
    conflicts: list[dict],
    dedupe_key: str | None = None,
) -> Command:
    """下达前置：草稿 + 版本匹配 + 冲突已确认；随后进入 ``issuing``。"""

    if not is_owner(command, actor_id):
        raise ApiError("FORBIDDEN", "只有指令创建者可以下达")
    if command.status != DRAFT:
        raise ApiError(
            "WORKFLOW_CONFLICT", "当前状态不允许下达", details={"status": command.status}
        )
    if int(expected_version) != int(command.version):
        raise ApiError(
            "VERSION_CONFLICT",
            details={"expected": expected_version, "current": command.version},
        )
    if conflicts and not conflict_acknowledged:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "存在活动指令冲突，必须确认后才能下达",
            details={"conflicts": [item["command_no"] for item in conflicts]},
        )

    record_conflict_check(
        db,
        command,
        checked_by=actor_id,
        conflicts=conflicts,
        decision="proceed" if conflicts and conflict_acknowledged else "proceed",
        reason="acknowledged" if conflicts else "no_conflict",
    )
    command.status = ISSUING
    command.last_request_id = dedupe_key
    command.version = int(command.version) + 1
    command.updated_by = actor_id
    command.updated_at = _now()
    db.commit()
    db.refresh(command)
    return command


def attach_assignments(
    db: Session,
    command: Command,
    *,
    actor_id: str,
    created: list[dict],
) -> Command:
    """把 Execution 侧建好的个人分配写成本地摘要，并把状态推进到 ``issued``。"""

    if command.status not in {ISSUING, ISSUED}:
        raise ApiError(
            "WORKFLOW_CONFLICT", "指令不在下达流程中", details={"status": command.status}
        )
    existing = {item.assignment_id: item for item in command.assignments}
    for item in created:
        assignment_id = str(item["id"])
        if assignment_id in existing:
            continue
        db.add(
            CommandAssignment(
                command_id=command.id,
                assignment_id=assignment_id,
                executor_id=str(item["executor_id"]),
                status=str(item.get("status") or AssignmentStatus.PENDING.value),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
    db.flush()
    db.refresh(command)

    command.status = recompute_status(command.assignments)
    command.issued_at = _now()
    command.version = int(command.version) + 1
    command.updated_by = actor_id
    command.updated_at = _now()
    db.commit()
    db.refresh(command)
    return command


def mark_compensation(
    db: Session, command: Command, *, actor_id: str, reason: str
) -> Command:
    command.status = COMPENSATION
    command.updated_by = actor_id
    command.updated_at = _now()
    db.commit()
    db.refresh(command)
    return command


def cancel_command(
    db: Session, command: Command, *, actor_id: str, expected_version: int, reason: str
) -> Command:
    if not is_owner(command, actor_id):
        raise ApiError("FORBIDDEN", "只有指令创建者可以取消")
    if command.status not in CANCELLABLE_STATUSES:
        raise ApiError(
            "WORKFLOW_CONFLICT", "当前状态不允许取消", details={"status": command.status}
        )
    if int(expected_version) != int(command.version):
        raise ApiError(
            "VERSION_CONFLICT",
            details={"expected": expected_version, "current": command.version},
        )
    command.status = CANCELLED
    command.cancelled_at = _now()
    command.cancel_reason = reason
    command.version = int(command.version) + 1
    command.updated_by = actor_id
    command.updated_at = _now()
    for item in command.assignments:
        if item.status not in {
            AssignmentStatus.COMPLETED.value,
            AssignmentStatus.FAILED.value,
            AssignmentStatus.REJECTED.value,
        }:
            item.status = AssignmentStatus.CANCELLED.value
            item.updated_at = _now()
            item.updated_by = actor_id
    db.commit()
    db.refresh(command)
    return command


def apply_assignment_state(
    db: Session,
    command: Command,
    *,
    assignment_id: str,
    executor_id: str,
    status: str,
) -> Command:
    """Execution 侧回写个人状态；在同一事务内重算总体状态（决策 D-01）。"""

    target = next(
        (item for item in command.assignments if item.assignment_id == assignment_id), None
    )
    if target is None:
        raise ApiError("RESOURCE_NOT_FOUND", "该指令下没有这个分配", details={"assignment_id": assignment_id})
    if target.executor_id != executor_id:
        raise ApiError("INVALID_REQUEST", "分配与执行员不匹配")
    if target.status == status:
        # 幂等：重复回写不翻转总体状态
        return command

    target.status = status
    target.updated_at = _now()
    target.version = int(target.version) + 1

    command.status = recompute_status(command.assignments)
    command.updated_at = _now()
    command.version = int(command.version) + 1
    db.commit()
    db.refresh(command)
    return command


def status_view(command: Command) -> dict[str, object]:
    return {
        "command_id": command.id,
        "status": command.status,
        "assignments": [assignment_summary_view(item) for item in command.assignments],
        "updated_at": iso(command.updated_at),
    }
