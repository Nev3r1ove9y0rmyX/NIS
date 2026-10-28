"""``nis_execution`` Schema：个人执行分配、执行证据。

逐列对应 ``docs/data-model.md`` 第 8 节。本服务只维护个人状态，不计算指令总体状态。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from nis_shared.enums import AssignmentStatus, Priority
from nis_shared.models import Base, DateTime3, HeadFieldsMixin, new_uuid, utcnow, uuid_pk


class ExecutionAssignment(Base, HeadFieldsMixin):
    __tablename__ = "execution_assignments"

    id = uuid_pk()
    #: 指令 UUID（跨服务引用，不建外键）。
    command_id = Column(String(36), nullable=False)
    command_title_snapshot = Column(String(200), nullable=False)
    command_content_snapshot = Column(Text, nullable=True)
    priority = Column(String(16), nullable=False, default=Priority.NORMAL.value)
    deadline = Column(DateTime3, nullable=True)
    executor_id = Column(String(36), nullable=False)
    status = Column(
        String(16), nullable=False, default=AssignmentStatus.PENDING.value, server_default="pending"
    )
    accepted_at = Column(DateTime3, nullable=True)
    started_at = Column(DateTime3, nullable=True)
    completed_at = Column(DateTime3, nullable=True)
    reject_reason = Column(String(500), nullable=True)
    #: ``success`` / ``failure`` / ``partial``，只在完成或失败提交时写入。
    result_outcome = Column(String(16), nullable=True)
    result_summary = Column(String(2000), nullable=True)
    result_detail = Column(Text, nullable=True)
    reported_at = Column(DateTime3, nullable=True)
    reported_by = Column(String(36), nullable=True)
    #: 结果提交幂等键：网络重试不得生成第二份结果。
    idempotency_key = Column(String(128), nullable=True)

    evidence = relationship("ExecutionEvidence", back_populates="assignment")

    __table_args__ = (
        Index("uq_execution_assignments_command_executor", "command_id", "executor_id", unique=True),
        Index("ix_execution_assignments_executor_status_updated", "executor_id", "status", "updated_at"),
        Index("uq_execution_assignments_idempotency_key", "idempotency_key", unique=True),
    )


class ExecutionEvidence(Base):
    """只追加表：不设 ``version`` / ``updated_*``（数据模型 1.3）。"""

    __tablename__ = "execution_evidence"

    id = Column(String(36), primary_key=True, default=new_uuid)
    assignment_id = Column(String(36), ForeignKey("execution_assignments.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    media_type = Column(String(127), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    sha256 = Column(String(64), nullable=False)
    storage_ref = Column(String(512), nullable=False)
    uploaded_by = Column(String(36), nullable=False)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    assignment = relationship("ExecutionAssignment", back_populates="evidence")

    __table_args__ = (Index("ix_execution_evidence_assignment_id", "assignment_id"),)
