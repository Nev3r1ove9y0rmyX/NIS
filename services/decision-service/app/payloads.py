"""决策指令的请求体（字段与长度对齐 decision-service.yaml）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

PRIORITY = "^(normal|urgent)$"
ASSIGNMENT_STATUS = "^(pending|accepted|executing|completed|failed|rejected|cancelled)$"


class CommandCreate(BaseModel):
    decision_maker_id: str = Field(min_length=36, max_length=36)
    organization_id: str = Field(min_length=36, max_length=36)
    title: str = Field(min_length=2, max_length=200)
    objective: str = Field(min_length=2, max_length=500)
    content: str = Field(min_length=10, max_length=8000)
    priority: str = Field(pattern=PRIORITY)
    deadline: datetime | None = None
    source_report_id: str = Field(min_length=36, max_length=36)


class CommandPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    objective: str | None = Field(default=None, min_length=2, max_length=500)
    content: str | None = Field(default=None, min_length=10, max_length=8000)
    priority: str | None = Field(default=None, pattern=PRIORITY)
    deadline: datetime | None = None


class CommandIssue(BaseModel):
    expected_version: int = Field(ge=1)
    executor_ids: list[str] = Field(min_length=1)
    conflict_acknowledged: bool = False


class CommandConfirmIssue(BaseModel):
    expected_version: int = Field(ge=1)
    assignments: list[dict] = Field(default_factory=list)


class CommandCancel(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=500)


class AssignmentState(BaseModel):
    assignment_id: str = Field(min_length=36, max_length=36)
    executor_id: str = Field(min_length=36, max_length=36)
    status: str = Field(pattern=ASSIGNMENT_STATUS)
