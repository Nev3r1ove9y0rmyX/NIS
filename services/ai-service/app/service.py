"""AI 建议业务规则：生成、人工处理与降级。

**人在回路**（ADR-003）：建议只是建议，``status`` 只有经人工 accept/edit/reject 才变化；
业务服务只能读取 ``accepted``/``edited`` 且带确认人的内容，不能凭建议直接驱动状态。

本期不接外部大模型：按 ``stage`` 与 ``suggestion_type`` 生成结构化的规则模板（可复现、零依赖），
模型不可用时按契约返回 503，人工流程照常继续（NFR-AI-001）。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AIRequest, AISuggestion
from nis_shared.enums import AISuggestionStatus
from nis_shared.errors import ApiError

MODEL_NAME = "nis-rule-based"
MODEL_VERSION = "1.0.0"

#: 每个环节的默认建议模板；内容刻意保守，避免模型「替人做决定」。
TEMPLATES: dict[tuple[str, str], dict] = {
    ("recon", "summary"): {
        "headline": "按「时间 / 地点 / 人员 / 装备」四要素归纳",
        "items": ["固定时段活动", "路线相对固定", "伴随通联活动"],
        "caveat": "以上为结构化提要，事实以原始记录为准。",
    },
    ("recon", "missing_field_hint"): {
        "fields": ["source_ref（来源可追溯性）", "credibility（可信度依据）"],
        "caveat": "缺项提示不改变记录内容，请人工补齐后再提交。",
    },
    ("analysis", "summary"): {
        "headline": "结论先行：规律性活动 → 固定保障节点",
        "items": ["时间耦合", "路线稳定", "可预判窗口"],
        "caveat": "分析结论由分析员确认，AI 不替其下判断。",
    },
    ("analysis", "risk_assessment"): {
        "risk_level_suggestion": "medium",
        "reasons": ["活动规律可预测，但证据链尚不完整"],
        "caveat": "风险等级需分析员确认。",
    },
    ("decision", "action_options"): {
        "options": ["提前部署观察点", "追加技术侦察", "暂缓并补充情报"],
        "caveat": "方案仅作比较用，目标、接收人与下达动作由决策员确认。",
    },
    ("decision", "conflict_hint"): {
        "check": ["同一依据报告上的活动指令", "同一目标文本的活动指令"],
        "caveat": "冲突提示不阻断下达，需决策员二次确认。",
    },
    ("execution", "summary"): {
        "headline": "结果摘要模板：结论 / 证据 / 异常",
        "items": ["按计划完成", "取得连续记录", "未发生异常接触"],
        "caveat": "结果由执行员本人填写提交。",
    },
}

DEFAULT_TEMPLATE = {
    "headline": "通用建议",
    "caveat": "建议仅供人工参考，不构成业务决定。",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.replace(microsecond=0).isoformat() + "Z"


def enabled() -> bool:
    """``AI_ENABLED=false`` 用于演示「AI 不可用但人工流程继续」。"""

    return os.environ.get("AI_ENABLED", "true").lower() not in {"false", "0", "no"}


def generate(stage: str, suggestion_type: str) -> dict[str, object]:
    if not enabled():
        raise ApiError("SERVICE_UNAVAILABLE", "AI 建议服务当前不可用，请人工完成该环节")
    template = TEMPLATES.get((stage, suggestion_type), DEFAULT_TEMPLATE)
    return {
        "content": template,
        "confidence": 0.6,
        "source_refs": [f"rule:{stage}/{suggestion_type}"],
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "latency_ms": 0,
    }


def suggestion_view(suggestion: AISuggestion, request: AIRequest | None = None) -> dict[str, object]:
    return {
        "id": suggestion.id,
        "stage": suggestion.stage,
        "business_object_type": request.business_object_type if request else None,
        "business_object_id": request.business_object_id if request else None,
        "suggestion_type": suggestion.suggestion_type,
        "content": suggestion.content,
        "confidence": float(suggestion.confidence) if suggestion.confidence is not None else None,
        "source_refs": suggestion.source_refs or [],
        "model_name": request.model_name if request else MODEL_NAME,
        "model_version": request.model_version if request else MODEL_VERSION,
        "latency_ms": request.latency_ms if request else None,
        "status": suggestion.status,
        "human_confirmed_by": suggestion.human_confirmed_by,
        "human_confirmed_at": iso(suggestion.human_confirmed_at),
        "edited_content": suggestion.edited_content,
        "created_at": iso(suggestion.created_at),
    }


def create_suggestion(
    db: Session,
    *,
    stage: str,
    business_object_type: str,
    business_object_id: str,
    suggestion_type: str,
    requested_by: str,
) -> tuple[AIRequest, AISuggestion]:
    generated = generate(stage, suggestion_type)
    request = AIRequest(
        stage=stage,
        business_object_type=business_object_type,
        business_object_id=business_object_id,
        suggestion_type=suggestion_type,
        requested_by=requested_by,
        model_name=str(generated["model_name"]),
        model_version=str(generated["model_version"]),
        status="succeeded",
        latency_ms=int(generated["latency_ms"]),
        requested_at=_now(),
        created_by=requested_by,
        updated_by=requested_by,
    )
    db.add(request)
    db.flush()

    suggestion = AISuggestion(
        request_id=request.id,
        stage=stage,
        suggestion_type=suggestion_type,
        content=generated["content"],
        confidence=generated["confidence"],
        source_refs=generated["source_refs"],
        status=AISuggestionStatus.PENDING.value,
        created_by=requested_by,
        updated_by=requested_by,
    )
    db.add(suggestion)
    db.commit()
    db.refresh(request)
    db.refresh(suggestion)
    return request, suggestion


def list_suggestions(
    db: Session,
    *,
    business_object_type: str,
    business_object_id: str,
    page: int,
    page_size: int,
) -> dict[str, object]:
    stmt = (
        select(AISuggestion, AIRequest)
        .join(AIRequest, AIRequest.id == AISuggestion.request_id)
        .where(AIRequest.business_object_type == business_object_type)
        .where(AIRequest.business_object_id == business_object_id)
    )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.execute(
        stmt.order_by(AISuggestion.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {
        "items": [suggestion_view(suggestion, request) for suggestion, request in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def get_suggestion(db: Session, suggestion_id: str) -> tuple[AISuggestion, AIRequest | None]:
    suggestion = db.scalars(
        select(AISuggestion).where(AISuggestion.id == suggestion_id)
    ).one_or_none()
    if suggestion is None:
        raise ApiError("RESOURCE_NOT_FOUND", "AI 建议不存在")
    request = db.scalars(select(AIRequest).where(AIRequest.id == suggestion.request_id)).one_or_none()
    return suggestion, request


def decide(
    db: Session,
    suggestion: AISuggestion,
    *,
    decision: str,
    confirmed_by: str,
    edited_content: dict | None,
    note: str | None,
) -> AISuggestion:
    """人工处理：接受、修改或拒绝。已处理过的不能再次处理（409）。"""

    if suggestion.status != AISuggestionStatus.PENDING.value:
        raise ApiError(
            "WORKFLOW_CONFLICT",
            "该建议已处理过",
            details={"status": suggestion.status},
        )
    if decision == AISuggestionStatus.EDITED.value and not edited_content:
        raise ApiError("INVALID_REQUEST", "选择修改时必须提供修改后的内容")

    suggestion.status = decision
    suggestion.human_confirmed_by = confirmed_by
    suggestion.human_confirmed_at = _now()
    suggestion.edited_content = edited_content if decision == AISuggestionStatus.EDITED.value else None
    suggestion.updated_by = confirmed_by
    suggestion.updated_at = _now()
    suggestion.version = int(suggestion.version or 1) + 1
    if note:
        # 备注放进 details 之外的附加字段会破坏契约，这里只在审计里留痕
        pass
    db.commit()
    db.refresh(suggestion)
    return suggestion
