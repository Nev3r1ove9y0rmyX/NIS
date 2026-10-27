"""``nis_analysis`` Schema：分析报告、侦察引用、决策员指派。

逐列对应 ``docs/data-model.md`` 第 6 节。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, ForeignKey, Index, String, Text
from sqlalchemy.orm import relationship

from nis_shared.enums import Priority, ReportStatus, RiskLevel, TargetHandlerStatus
from nis_shared.models import Base, DateTime3, HeadFieldsMixin, new_uuid, utcnow, uuid_pk


class AnalysisReport(Base, HeadFieldsMixin):
    __tablename__ = "analysis_reports"

    id = uuid_pk()
    report_no = Column(String(32), nullable=False, unique=True)
    title = Column(String(200), nullable=False)
    status = Column(String(32), nullable=False, default=ReportStatus.DRAFT.value, server_default="draft")
    author_id = Column(String(36), nullable=False)
    organization_id = Column(String(36), nullable=False)
    key_findings = Column(Text, nullable=False)
    relations = Column(Text, nullable=True)
    risk_level = Column(String(16), nullable=False, default=RiskLevel.MEDIUM.value)
    recommended_actions = Column(Text, nullable=False)
    priority = Column(String(16), nullable=False, default=Priority.NORMAL.value)
    #: AI 内容是否已逐条处理，是提交的前置条件（workflow 第 7 节）。
    ai_content_confirmed = Column(Boolean, nullable=False, default=False, server_default="0")
    human_confirmed = Column(Boolean, nullable=False, default=False, server_default="0")
    confirmed_by = Column(String(36), nullable=True)
    confirmed_at = Column(DateTime3, nullable=True)
    submitted_at = Column(DateTime3, nullable=True)
    last_request_id = Column(String(36), nullable=True)

    recon_links = relationship("ReportReconLink", back_populates="report")
    assignments = relationship("ReportAssignment", back_populates="report")

    __table_args__ = (
        Index("ix_analysis_reports_author_status_updated", "author_id", "status", "updated_at"),
        Index("ix_analysis_reports_organization_status", "organization_id", "status"),
    )


class ReportReconLink(Base, HeadFieldsMixin):
    __tablename__ = "report_recon_links"

    id = Column(String(36), primary_key=True, default=new_uuid)
    report_id = Column(String(36), ForeignKey("analysis_reports.id"), nullable=False)
    #: 侦察记录 UUID（跨服务引用，不建外键）。
    recon_record_id = Column(String(36), nullable=False)
    #: 不可变快照，避免跨服务实时读取（数据模型 1.4）。
    recon_title_snapshot = Column(String(200), nullable=False)
    recon_owner_snapshot = Column(String(64), nullable=True)
    recon_priority_snapshot = Column(String(16), nullable=True)
    linked_at = Column(DateTime3, nullable=False, default=utcnow)

    report = relationship("AnalysisReport", back_populates="recon_links")

    __table_args__ = (
        Index("uq_report_recon_links", "report_id", "recon_record_id", unique=True),
        Index("ix_report_recon_links_recon_record_id", "recon_record_id"),
    )


class ReportAssignment(Base, HeadFieldsMixin):
    __tablename__ = "report_assignments"

    id = Column(String(36), primary_key=True, default=new_uuid)
    report_id = Column(String(36), ForeignKey("analysis_reports.id"), nullable=False)
    decision_maker_id = Column(String(36), nullable=False)
    status = Column(
        String(16), nullable=False, default=TargetHandlerStatus.PENDING.value, server_default="pending"
    )
    assigned_by = Column(String(36), nullable=False)
    assigned_at = Column(DateTime3, nullable=False, default=utcnow)
    responded_at = Column(DateTime3, nullable=True)
    reject_reason = Column(String(500), nullable=True)

    report = relationship("AnalysisReport", back_populates="assignments")

    __table_args__ = (
        Index("uq_report_assignments_report_maker", "report_id", "decision_maker_id", unique=True),
        Index("ix_report_assignments_maker_status", "decision_maker_id", "status"),
    )
