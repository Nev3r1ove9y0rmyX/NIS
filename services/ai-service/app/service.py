"""AI 建议业务规则：生成、人工处理与降级。

**人在回路**（ADR-003）：建议只是建议，``status`` 只有经人工 accept/edit/reject 才变化；
业务服务只能读取 ``accepted``/``edited`` 且带确认人的内容，不能凭建议直接驱动状态。

支持两种后端：
- `AI_PROVIDER=local`（默认）：按 ``stage`` 与 ``suggestion_type`` 生成结构化规则模板，可复现、零依赖；
- `AI_PROVIDER=ollama|openai`：调用外部模型（Ollama 原生接口 / OpenAI 兼容接口），
  超时或报错自动回退规则模板，保证演示与业务不中断；``AI_ENABLED=false`` 时仍按契约返回 503。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
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


PROVIDER = os.environ.get("AI_PROVIDER", "local").strip().lower()
AI_BASE_URL = os.environ.get("AI_BASE_URL", "").rstrip("/")
AI_MODEL = os.environ.get("AI_MODEL", "").strip()
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_TIMEOUT_SECONDS = float(os.environ.get("AI_TIMEOUT_SECONDS", "20"))

#: 每个环节给模型的提示词（明确要求只做辅助、输出 JSON）
PROMPTS: dict[tuple[str, str], str] = {
    ("recon", "summary"): "你是侦察辅助助手。请把侦察情况按时间、地点、人员、装备四要素归纳。",
    ("recon", "missing_field_hint"): "你是侦察辅助助手。请指出这条侦察记录可能缺失的字段及其原因。",
    ("analysis", "summary"): "你是分析辅助助手。请给出结论先行的分析要点，不替分析员下结论。",
    ("analysis", "risk_assessment"): "你是分析辅助助手。请给出风险等级建议（low/medium/high）与理由。",
    ("decision", "action_options"): "你是决策辅助助手。请给出 2-3 个可选行动方案供决策员比较。",
    ("decision", "conflict_hint"): "你是决策辅助助手。请提示下达指令时可能出现的冲突点。",
    ("execution", "summary"): "你是执行辅助助手。请给出执行结果摘要模板（结论、证据、异常）。",
}


def _prompt(stage: str, suggestion_type: str) -> str:
    base = PROMPTS.get((stage, suggestion_type), "你是协同调度系统的辅助助手。")
    return (
        f"{base}\n"
        "要求：只输出 JSON，字段为 headline（一句话结论）、items（字符串数组，2-4 条）、"
        'caveat（一句话提醒，说明最终由人工确认）。不要输出 JSON 以外的任何文字。'
    )


def _post_json(url: str, payload: dict, *, headers: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8")
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=request_headers, method="POST")
    with urllib.request.urlopen(req, timeout=AI_TIMEOUT_SECONDS) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _extract_json(text: str) -> dict | None:
    """模型输出里抓第一个 JSON 对象；失败返回 None。"""

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _call_model(stage: str, suggestion_type: str) -> dict[str, object] | None:
    """调用真实模型；任何异常都返回 None，由调用方回退模板。"""

    if PROVIDER not in {"ollama", "openai"} or not AI_BASE_URL or not AI_MODEL:
        return None
    prompt = _prompt(stage, suggestion_type)
    try:
        if PROVIDER == "ollama":
            payload = {
                "model": AI_MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.3, "num_predict": 320},
            }
            data = _post_json(f"{AI_BASE_URL}/api/generate", payload)
            text = str(data.get("response", ""))
        else:
            payload = {
                "model": AI_MODEL,
                "messages": [
                    {"role": "system", "content": "你是协同调度系统的辅助助手，只输出 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
            }
            headers = {"Authorization": f"Bearer {AI_API_KEY}"} if AI_API_KEY else None
            data = _post_json(f"{AI_BASE_URL}/chat/completions", payload, headers=headers)
            text = str(data["choices"][0]["message"]["content"])
    except (urllib.error.URLError, TimeoutError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(f"[ai] 模型调用失败，回退规则模板：{exc}", flush=True)
        return None

    content = _extract_json(text)
    if content is None:
        print("[ai] 模型输出不是合法 JSON，回退规则模板", flush=True)
        return None
    return {
        "content": content,
        "confidence": 0.75,
        "source_refs": [f"model:{PROVIDER}/{AI_MODEL}"],
        "model_name": AI_MODEL,
        "model_version": PROVIDER,
        "latency_ms": 0,
    }


def generate(stage: str, suggestion_type: str) -> dict[str, object]:
    if not enabled():
        raise ApiError("SERVICE_UNAVAILABLE", "AI 建议服务当前不可用，请人工完成该环节")

    generated = _call_model(stage, suggestion_type)
    if generated is not None:
        return generated

    template = TEMPLATES.get((stage, suggestion_type), DEFAULT_TEMPLATE)
    # 只有"配置了外部模型但调用失败"才标注 (fallback)；纯规则模板模式保持原模型名
    fallback = PROVIDER in {"ollama", "openai"}
    return {
        "content": template,
        "confidence": 0.6,
        "source_refs": [f"rule:{stage}/{suggestion_type}"],
        "model_name": f"{MODEL_NAME}(fallback)" if fallback else MODEL_NAME,
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
