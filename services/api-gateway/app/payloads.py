"""Gateway 请求体模型：字段与长度按 api-gateway.yaml 校验，校验失败统一 422。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class CreateUserRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    display_name: str = Field(min_length=1, max_length=64)
    organization_id: str = Field(min_length=36, max_length=36)
    role_codes: list[str] = Field(min_length=1)


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=64)
    organization_id: str | None = Field(default=None, min_length=36, max_length=36)
    status: str | None = Field(default=None, pattern="^(active|disabled|locked)$")
    new_password: str | None = Field(default=None, min_length=8, max_length=128)


class AssignRoleRequest(BaseModel):
    role_code: str = Field(min_length=1, max_length=32)
    expires_at: datetime | None = None


class CreateRoleRequest(BaseModel):
    code: str = Field(min_length=1, max_length=32)
    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class ReplacePermissionsRequest(BaseModel):
    permission_codes: list[str]


class CreateOrganizationRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parent_id: str | None = Field(default=None, min_length=36, max_length=36)
    unit_type: str = Field(
        default="command", pattern="^(command|staff|recon_team|analysis_team|execution_team)$"
    )
    sort_order: int = 0
