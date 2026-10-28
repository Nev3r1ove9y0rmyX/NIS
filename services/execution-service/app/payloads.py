"""执行分配的请求体（字段与长度对齐 execution-service.yaml）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

PRIORITY = "^(normal|urgent)$"
OUTCOME = "^(success|failure|partial)$"


class EvidenceInput(BaseModel):
    file_name: str = Field(max_length=255)
    media_type: str = Field(max_length=127)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")


class AssignmentCreateBatch(BaseModel):
    command_id: str = Field(min_length=36, max_length=36)
    command_title: str = Field(min_length=1, max_length=200)
    command_content: str | None = Field(default=None, max_length=8000)
    priority: str = Field(pattern=PRIORITY)
    deadline: datetime | None = None
    executor_ids: list[str] = Field(min_length=1)
    created_by: str = Field(min_length=36, max_length=36)


class TransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class RejectRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=500)


class CompleteRequest(BaseModel):
    expected_version: int = Field(ge=1)
    outcome: str = Field(pattern=OUTCOME)
    summary: str = Field(min_length=1, max_length=2000)
    detail: str | None = Field(default=None, max_length=8000)
    evidence: list[EvidenceInput] = Field(default_factory=list)
