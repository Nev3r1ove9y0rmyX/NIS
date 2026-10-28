"""侦察记录的请求体（字段与长度对齐 recon-service.yaml）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

SOURCE_TYPES = "^(osint|sensor|report|document|other)$"
CREDIBILITY = "^(high|medium|low|unverified)$"
PRIORITY = "^(normal|urgent)$"


class EvidenceInput(BaseModel):
    file_name: str = Field(max_length=255)
    media_type: str = Field(max_length=127)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")


class ReconRecordCreate(BaseModel):
    owner_id: str = Field(min_length=36, max_length=36)
    organization_id: str | None = Field(default=None, min_length=36, max_length=36)
    title: str = Field(min_length=2, max_length=200)
    source_type: str = Field(pattern=SOURCE_TYPES)
    source_ref: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=10, max_length=8000)
    credibility: str = Field(pattern=CREDIBILITY)
    priority: str = Field(pattern=PRIORITY)
    evidence: list[EvidenceInput] = Field(default_factory=list)


class ReconRecordPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    source_type: str | None = Field(default=None, pattern=SOURCE_TYPES)
    source_ref: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=10, max_length=8000)
    credibility: str | None = Field(default=None, pattern=CREDIBILITY)
    priority: str | None = Field(default=None, pattern=PRIORITY)


class ReconSubmit(BaseModel):
    expected_version: int = Field(ge=1)
    analyst_ids: list[str] = Field(min_length=1)
    priority: str | None = Field(default=None, pattern=PRIORITY)


class ConfirmSubmission(BaseModel):
    expected_version: int = Field(ge=1)


class MarkCompensation(BaseModel):
    request_id: str = Field(min_length=36, max_length=36)
    failed_step: str = Field(min_length=1, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class AnalysisStateUpdate(BaseModel):
    analyst_id: str = Field(min_length=36, max_length=36)
    assignment_status: str = Field(pattern="^(pending|in_progress|completed|rejected)$")
    reject_reason: str | None = Field(default=None, max_length=500)
