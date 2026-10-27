"""``nis_ai`` Schema：AI 请求与建议。

逐列对应 ``docs/data-model.md`` 第 9 节。建议不能直接驱动业务状态（ADR-003）。
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Index, Integer, JSON, Numeric, String
from sqlalchemy.orm import relationship

from nis_shared.enums import AISuggestionStatus
from nis_shared.models import Base, DateTime3, HeadFieldsMixin, new_uuid, utcnow, uuid_pk


class AIRequest(Base, HeadFieldsMixin):
    __tablename__ = "ai_requests"

    id = uuid_pk()
    stage = Column(String(16), nullable=False)
    business_object_type = Column(String(32), nullable=False)
    #: 来源对象 UUID，只作引用，不读取其他服务 Schema。
    business_object_id = Column(String(36), nullable=False)
    suggestion_type = Column(String(32), nullable=False)
    requested_by = Column(String(36), nullable=False)
    #: 输入摘要，不保存越权原文。
    input_digest = Column(String(64), nullable=True)
    model_name = Column(String(64), nullable=True)
    model_version = Column(String(64), nullable=True)
    #: ``pending`` / ``succeeded`` / ``failed`` / ``timeout``
    status = Column(String(16), nullable=False, default="pending", server_default="pending")
    latency_ms = Column(Integer, nullable=True)
    error_code = Column(String(64), nullable=True)
    requested_at = Column(DateTime3, nullable=False, default=utcnow)

    suggestions = relationship("AISuggestion", back_populates="request")

    __table_args__ = (
        Index(
            "ix_ai_requests_object_requested",
            "business_object_type",
            "business_object_id",
            "requested_at",
        ),
    )


class AISuggestion(Base, HeadFieldsMixin):
    __tablename__ = "ai_suggestions"

    id = uuid_pk()
    request_id = Column(String(36), ForeignKey("ai_requests.id"), nullable=False)
    stage = Column(String(16), nullable=False)
    suggestion_type = Column(String(32), nullable=False)
    #: 结构化建议原文，不可直接驱动状态。
    content = Column(JSON, nullable=False)
    confidence = Column(Numeric(4, 3), nullable=True)
    source_refs = Column(JSON, nullable=True)
    status = Column(
        String(16), nullable=False, default=AISuggestionStatus.PENDING.value, server_default="pending"
    )
    human_confirmed_by = Column(String(36), nullable=True)
    human_confirmed_at = Column(DateTime3, nullable=True)
    edited_content = Column(JSON, nullable=True)

    request = relationship("AIRequest", back_populates="suggestions")

    __table_args__ = (
        Index("ix_ai_suggestions_request_id", "request_id"),
        Index("ix_ai_suggestions_status", "status"),
    )
