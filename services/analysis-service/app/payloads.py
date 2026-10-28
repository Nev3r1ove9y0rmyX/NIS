"""分析报告的请求体（字段与长度对齐 analysis-service.yaml）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

PRIORITY = "^(normal|urgent)$"
RISK = "^(low|medium|high)$"


class ReconSnapshotInput(BaseModel):
    recon_record_id: str = Field(min_length=36, max_length=36)
    recon_title_snapshot: str = Field(min_length=1, max_length=200)
    recon_owner_snapshot: str | None = Field(default=None, max_length=64)
    recon_priority_snapshot: str | None = Field(default=None, pattern=PRIORITY)
    linked_at: datetime | None = None


class ReportCreate(BaseModel):
    author_id: str = Field(min_length=36, max_length=36)
    organization_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=2, max_length=200)
    recon_record_ids: list[str] = Field(min_length=1)
    recon_snapshots: list[ReconSnapshotInput] = Field(default_factory=list)
    key_findings: str = Field(min_length=10, max_length=8000)
    relations: str | None = Field(default=None, max_length=8000)
    risk_level: str = Field(pattern=RISK)
    recommended_actions: str = Field(min_length=1, max_length=8000)
    priority: str = Field(pattern=PRIORITY)


class ReportPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    key_findings: str | None = Field(default=None, min_length=10, max_length=8000)
    relations: str | None = Field(default=None, max_length=8000)
    risk_level: str | None = Field(default=None, pattern=RISK)
    recommended_actions: str | None = Field(default=None, min_length=1, max_length=8000)
    priority: str | None = Field(default=None, pattern=PRIORITY)


class ReportSubmit(BaseModel):
    expected_version: int = Field(ge=1)
    decision_maker_ids: list[str] = Field(min_length=1)
    ai_content_confirmed: bool = True


class ReportConfirmSubmission(BaseModel):
    expected_version: int = Field(ge=1)


class ReportDecisionState(BaseModel):
    state: str = Field(pattern="^(decided|rejected|under_decision)$")
    command_id: str | None = Field(default=None, min_length=36, max_length=36)
    reason: str | None = Field(default=None, max_length=500)
