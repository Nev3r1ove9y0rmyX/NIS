"""AI 建议的请求体（字段对齐 ai-service.yaml）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

STAGE = "^(recon|analysis|decision|execution)$"
OBJECT_TYPE = "^(recon_record|analysis_report|command|assignment)$"
SUGGESTION_TYPE = (
    "^(summary|classification|missing_field_hint|entity_relation|risk_assessment|action_options|conflict_hint)$"
)


class SuggestionCreate(BaseModel):
    stage: str = Field(pattern=STAGE)
    business_object_type: str = Field(pattern=OBJECT_TYPE)
    business_object_id: str = Field(min_length=36, max_length=36)
    suggestion_type: str = Field(pattern=SUGGESTION_TYPE)
    requested_by: str = Field(min_length=36, max_length=36)


class SuggestionDecision(BaseModel):
    decision: str = Field(pattern="^(accepted|edited|rejected)$")
    confirmed_by: str = Field(min_length=36, max_length=36)
    edited_content: dict | None = None
    note: str | None = Field(default=None, max_length=500)
