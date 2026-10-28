"""``nis_decision`` Schema：决策指令、个人分配摘要、冲突检查。

逐列对应 ``docs/data-model.md`` 第 7 节。``commands.status`` 只由本服务重算（决策 D-01）。
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, JSON, String, Text
from sqlalchemy.orm import relationship

from nis_shared.enums import AssignmentStatus, CommandStatus, Priority
from nis_shared.models import Base, DateTime3, HeadFieldsMixin, new_uuid, utcnow, uuid_pk


class Command(Base, HeadFieldsMixin):
    __tablename__ = "commands"

    id = uuid_pk()
    command_no = Column(String(32), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    objective = Column(String(500), nullable=False)
    content = Column(Text, nullable=False)
    priority = Column(String(16), nullable=False, default=Priority.NORMAL.value)
    deadline = Column(DateTime3, nullable=True)
    status = Column(String(32), nullable=False, default=CommandStatus.DRAFT.value, server_default="draft")
    decision_maker_id = Column(String(36), nullable=False)
    organization_id = Column(String(36), nullable=False)
    #: 依据报告 UUID（跨服务引用）。
    source_report_id = Column(String(36), nullable=False)
    issued_at = Column(DateTime3, nullable=True)
    cancelled_at = Column(DateTime3, nullable=True)
    cancel_reason = Column(String(500), nullable=True)
    last_request_id = Column(String(36), nullable=True)

    assignments = relationship("CommandAssignment", back_populates="command")
    conflict_checks = relationship("CommandConflictCheck", back_populates="command")

    __table_args__ = (
        Index("ix_commands_maker_status_updated", "decision_maker_id", "status", "updated_at"),
        Index("ix_commands_source_report_status", "source_report_id", "status"),
    )


class CommandAssignment(Base, HeadFieldsMixin):
    """Decision 侧保存的个人分配**状态摘要**，事实来源在 ``nis_execution``。"""

    __tablename__ = "command_assignments"

    id = Column(String(36), primary_key=True, default=new_uuid)
    command_id = Column(String(36), ForeignKey("commands.id"), nullable=False)
    #: Execution 侧分配 UUID。
    assignment_id = Column(String(36), nullable=False)
    executor_id = Column(String(36), nullable=False)
    status = Column(
        String(16), nullable=False, default=AssignmentStatus.PENDING.value, server_default="pending"
    )

    command = relationship("Command", back_populates="assignments")

    __table_args__ = (
        Index("uq_command_assignments_command_executor", "command_id", "executor_id", unique=True),
        Index("uq_command_assignments_assignment_id", "assignment_id", unique=True),
        Index("ix_command_assignments_executor_status", "executor_id", "status"),
    )


class CommandConflictCheck(Base, HeadFieldsMixin):
    __tablename__ = "command_conflict_checks"

    id = Column(String(36), primary_key=True, default=new_uuid)
    command_id = Column(String(36), ForeignKey("commands.id"), nullable=False)
    checked_at = Column(DateTime3, nullable=False, default=utcnow)
    checked_by = Column(String(36), nullable=False)
    conflict_type = Column(String(32), nullable=False)
    #: 命中的活动指令 UUID 数组。JSON 列不建索引：冲突查询固定按 ``command_id`` 与
    #: 活动时间窗过滤（见 migrations/0001 的说明），不做全表 JSON 检索。
    matched_command_ids = Column(JSON, nullable=False, default=list)
    #: ``proceed`` / ``cancel``
    decision = Column(String(16), nullable=False)
    reason = Column(String(500), nullable=True)

    command = relationship("Command", back_populates="conflict_checks")

    __table_args__ = (Index("ix_command_conflict_checks_command_id", "command_id"),)
