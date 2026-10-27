"""Gateway 管理路由：用户、角色、权限、组织（/api/v1/admin/*）。

入口级权限（iam:manage / organization:manage）在这里判断；下游 IAM 会独立再判一次，
两边都依赖同一份 IAM 权限数据，语义一致。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from app.payloads import (
    AssignRoleRequest,
    CreateOrganizationRequest,
    CreateRoleRequest,
    CreateUserRequest,
    ReplacePermissionsRequest,
    UpdateUserRequest,
)
from app.proxy import forward, forward_response
from app.routes_auth import organization_ref

router = APIRouter(prefix="/api/v1/admin", tags=["管理"])

IAM_MANAGE = "iam:manage"
ORG_MANAGE = "organization:manage"


def _user_summary(user: dict) -> dict:
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "status": user.get("status"),
        "organization": organization_ref(user.get("organization")),
        "roles": user.get("roles") or [],
    }


def _user_detail(user: dict) -> dict:
    detail = _user_summary(user)
    detail["permissions"] = user.get("permissions") or []
    detail["last_login_at"] = user.get("last_login_at")
    return detail


@router.get("/users", summary="用户列表")
def list_users(
    request: Request,
    status: str | None = Query(default=None),
    role_code: str | None = Query(default=None),
    organization_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    code, payload = forward(
        request,
        "GET",
        "/internal/v1/users",
        permission=IAM_MANAGE,
        params={
            "status": status,
            "role_code": role_code,
            "organization_id": organization_id,
            "page": page,
            "page_size": page_size,
        },
    )
    return JSONResponse(
        {
            "items": [_user_summary(u) for u in payload.get("items", [])],
            "page": payload.get("page", page),
            "page_size": payload.get("page_size", page_size),
            "total": payload.get("total", 0),
        },
        status_code=code,
    )


@router.post("/users", status_code=201, summary="创建用户")
def create_user(payload: CreateUserRequest, request: Request) -> JSONResponse:
    code, user = forward(
        request,
        "POST",
        "/internal/v1/users",
        permission=IAM_MANAGE,
        json_body=payload.model_dump(),
        status=201,
    )
    return JSONResponse(_user_detail(user), status_code=code)


@router.get("/users/{user_id}", summary="用户详情")
def get_user(user_id: str, request: Request) -> JSONResponse:
    code, user = forward(request, "GET", f"/internal/v1/users/{user_id}", permission=IAM_MANAGE)
    return JSONResponse(_user_detail(user), status_code=code)


@router.patch("/users/{user_id}", summary="更新用户")
def update_user(user_id: str, payload: UpdateUserRequest, request: Request) -> JSONResponse:
    code, user = forward(
        request,
        "PATCH",
        f"/internal/v1/users/{user_id}",
        permission=IAM_MANAGE,
        json_body=payload.model_dump(exclude_none=True),
    )
    return JSONResponse(_user_detail(user), status_code=code)


@router.get("/users/{user_id}/roles", summary="用户角色")
def list_user_roles(user_id: str, request: Request) -> JSONResponse:
    return forward_response(
        request, "GET", f"/internal/v1/users/{user_id}/roles", permission=IAM_MANAGE
    )


@router.post("/users/{user_id}/roles", status_code=201, summary="授予角色")
def assign_user_role(user_id: str, payload: AssignRoleRequest, request: Request) -> JSONResponse:
    code, binding = forward(
        request,
        "POST",
        f"/internal/v1/users/{user_id}/roles",
        permission=IAM_MANAGE,
        json_body=payload.model_dump(mode="json", exclude_none=True),
        status=201,
    )
    return JSONResponse(binding, status_code=code)


@router.delete("/users/{user_id}/roles/{role_code}", status_code=204, summary="撤销角色")
def revoke_user_role(user_id: str, role_code: str, request: Request) -> JSONResponse:
    forward(
        request,
        "DELETE",
        f"/internal/v1/users/{user_id}/roles/{role_code}",
        permission=IAM_MANAGE,
    )
    return JSONResponse(None, status_code=204)


@router.get("/roles", summary="角色列表")
def list_roles(request: Request) -> JSONResponse:
    return forward_response(request, "GET", "/internal/v1/roles", permission=IAM_MANAGE)


@router.post("/roles", status_code=201, summary="创建角色")
def create_role(payload: CreateRoleRequest, request: Request) -> JSONResponse:
    code, role = forward(
        request,
        "POST",
        "/internal/v1/roles",
        permission=IAM_MANAGE,
        json_body=payload.model_dump(),
        status=201,
    )
    return JSONResponse(role, status_code=code)


@router.put("/roles/{role_id}/permissions", summary="替换角色权限")
def replace_role_permissions(
    role_id: str, payload: ReplacePermissionsRequest, request: Request
) -> JSONResponse:
    code, role = forward(
        request,
        "PUT",
        f"/internal/v1/roles/{role_id}/permissions",
        permission=IAM_MANAGE,
        json_body=payload.model_dump(),
    )
    return JSONResponse(role, status_code=code)


@router.get("/permissions", summary="权限清单")
def list_permissions(request: Request) -> JSONResponse:
    return forward_response(request, "GET", "/internal/v1/permissions", permission=IAM_MANAGE)


@router.post("/organizations", status_code=201, summary="创建组织")
def create_organization(payload: CreateOrganizationRequest, request: Request) -> JSONResponse:
    code, org = forward(
        request,
        "POST",
        "/internal/v1/organizations",
        permission=ORG_MANAGE,
        json_body=payload.model_dump(),
        status=201,
    )
    return JSONResponse(
        {
            **organization_ref(org),
            "parent_id": org.get("parent_id"),
            "unit_type": org.get("unit_type"),
            "is_active": org.get("is_active"),
        },
        status_code=code,
    )
