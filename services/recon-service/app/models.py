"""``nis_recon`` Schema：侦察记录、分析员指派、证据元数据。

逐列对应 ``docs/data-model.md`` 第 5 节。
"""

from __future__ import annotations

from sqlalchemy import BigInteger, Column, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from nis_shared.enums import Credibility, Priority, ReconStatus, SourceType, TargetHandlerStatus
from nis_shared.models import Base, DateTime3, HeadFieldsMixin, new_uuid, utcnow, uuid_pk


class ReconRecord(Base, HeadFieldsMixin):
    __tablename__ = "recon_records"

    id = uuid_pk()
    #: 人可读编号 ``REC-YYYYMMDD-0001``，只用于展示，不做接口标识。
    record_no = Column(String(32), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    source_type = Column(String(32), nullable=False, default=SourceType.OTHER.value)
    #: 脱敏来源说明，不写真实敏感地址。
    source_ref = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    credibility = Column(String(16), nullable=False, default=Credibility.MEDIUM.value)
    priority = Column(String(16), nullable=False, default=Priority.NORMAL.value)
    status = Column(String(32), nullable=False, default=ReconStatus.DRAFT.value, server_default="draft")
    #: 侦察员 UUID（跨服务引用，不建外键）。
    owner_id = Column(String(36), nullable=False)
    organization_id = Column(String(36), nullable=False)
    submitted_at = Column(DateTime3, nullable=True)
    #: 最近一次提交的追踪 ID，便于把业务对象接回审计链。
    last_request_id = Column(String(36), nullable=True)

    assignments = relationship("ReconAssignment", back_populates="record")
    evidence = relationship("ReconEvidence", back_populates="record")

    __table_args__ = (
        Index("ix_recon_records_owner_status_updated", "owner_id", "status", "updated_at"),
        Index("ix_recon_records_organization_status", "organization_id", "status"),
        Index("ix_recon_records_last_request_id", "last_request_id"),
    )


class ReconAssignment(Base, HeadFieldsMixin):
    __tablename__ = "recon_assignments"

    id = Column(String(36), primary_key=True, default=new_uuid)
    record_id = Column(String(36), ForeignKey("recon_records.id"), nullable=False)
    analyst_id = Column(String(36), nullable=False)
    status = Column(
        String(16), nullable=False, default=TargetHandlerStatus.PENDING.value, server_default="pending"
    )
    assigned_by = Column(String(36), nullable=False)
    assigned_at = Column(DateTime3, nullable=False, default=utcnow)
    responded_at = Column(DateTime3, nullable=True)
    reject_reason = Column(String(500), nullable=True)

    record = relationship("ReconRecord", back_populates="assignments")

    __table_args__ = (
        Index("uq_recon_assignments_record_analyst", "record_id", "analyst_id", unique=True),
        Index("ix_recon_assignments_analyst_status", "analyst_id", "status"),
    )


class ReconEvidence(Base):
    """只追加表：不设 ``version`` / ``updated_*``（数据模型 1.3）。"""

    __tablename__ = "recon_evidence"

    id = Column(String(36), primary_key=True, default=new_uuid)
    record_id = Column(String(36), ForeignKey("recon_records.id"), nullable=False)
    file_name = Column(String(255), nullable=False)
    media_type = Column(String(127), nullable=False)
    size_bytes = Column(BigInteger, nullable=False, default=0, server_default="0")
    sha256 = Column(String(64), nullable=False)
    #: 受控存储引用，不落绝对路径（决策 D-02）。
    storage_ref = Column(String(512), nullable=False)
    uploaded_by = Column(String(36), nullable=False)
    created_at = Column(DateTime3, nullable=False, default=utcnow)

    record = relationship("ReconRecord", back_populates="evidence")

    __table_args__ = (
        Index("ix_recon_evidence_record_id", "record_id"),
        Index("ix_recon_evidence_sha256", "sha256"),
    )
