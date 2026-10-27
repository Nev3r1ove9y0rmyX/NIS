"""``nis_audit`` Schema：只追加的审计事件与调用链索引。

逐列对应 ``docs/data-model.md`` 第 10 节。业务账号对该 Schema 只有 ``SELECT``/``INSERT``
（决策 D-06），任何服务都不得 UPDATE/DELETE 审计记录。
"""

from __future__ import annotations

from sqlalchemy import Column, Index, JSON, String

from nis_shared.models import Base, DateTime3, UBigInt, utcnow


class AuditEvent(Base):
    __tablename__ = "audit_events"

    #: 单调递增主键，只为稳定排序；对外标识用 ``request_id``。
    id = Column(UBigInt, primary_key=True, autoincrement=True)
    request_id = Column(String(36), nullable=False)
    occurred_at = Column(DateTime3, nullable=False, default=utcnow)
    service = Column(String(64), nullable=False)
    event_type = Column(String(32), nullable=False)
    #: 最终操作者；禁止用服务账号替代。
    actor_user_id = Column(String(36), nullable=True)
    actor_role = Column(String(32), nullable=True)
    actor_organization_id = Column(String(36), nullable=True)
    #: 稳定动作名，例如 ``recon_record.submit``。
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(36), nullable=True)
    result = Column(String(16), nullable=False)
    error_code = Column(String(64), nullable=True)
    source_ip = Column(String(64), nullable=True)
    user_agent = Column(String(300), nullable=True)
    service_identity = Column(String(64), nullable=True)
    #: 结构化补充信息；禁止密码、Token、完整敏感正文。
    details = Column(JSON, nullable=True)
    #: 请求正文摘要，便于比对但不保存原文。
    payload_digest = Column(String(64), nullable=True)

    __table_args__ = (
        Index("ix_audit_events_request_id", "request_id", "id"),
        Index("ix_audit_events_resource", "resource_type", "resource_id", "id"),
        Index("ix_audit_events_actor", "actor_user_id", "occurred_at"),
        Index("ix_audit_events_occurred_at", "occurred_at"),
    )


class AuditTraceIndex(Base):
    """一次业务动作一行，用于快速还原跨服务调用链。"""

    __tablename__ = "audit_trace_index"

    request_id = Column(String(36), primary_key=True)
    root_action = Column(String(64), nullable=False)
    started_at = Column(DateTime3, nullable=False, default=utcnow)
    completed_at = Column(DateTime3, nullable=True)
    event_count = Column(UBigInt, nullable=False, default=0, server_default="0")
    outcome = Column(String(16), nullable=True)
