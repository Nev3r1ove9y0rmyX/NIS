"""IAM 路由：认证、用户/角色/权限/组织、候选接收人。

路由层只做三件事：取参数、调用 ``app.service``、写审计。所有业务判断在 service 里。
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import service
from app.models import Role
from app.auth_local import (
    get_db,
    iam_principal,
    require_permission_local,
    signing_key,
)
from app.payloads import (
    LoginRequest,
    OrganizationCreateRequest,
    RefreshRequest,
    ResolveUsersRequest,
    RoleAssignRequest,
    RoleCreateRequest,
    RolePermissionsRequest,
    UserCreateRequest,
    UserPatchRequest,
)
from nis_shared.auth import Principal
from nis_shared.errors import ApiError
from nis_shared.pagination import PageQuery, page_query

auth_router = APIRouter(tags=["认证"])
admin_router = APIRouter(tags=["用户与权限"])


def _audit(
    request: Request,
    action: str,
    result: str,
    *,
    actor: Principal | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    error_code: str | None = None,
    details: dict | None = None,
    event_type: str = "user_operation",
) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    audit.write(
        event_type=event_type,
        action=action,
        result=result,
        request_id=getattr(request.state, "request_id", ""),
        actor_user_id=actor.user_id if actor else None,
        actor_role=actor.role_context if actor else None,
        resource_type=resource_type,
        resource_id=resource_id,
        error_code=error_code,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


# --------------------------------------------------------------------------- 认证


@auth_router.post("/internal/v1/auth/login", summary="校验用户名密码并签发令牌")
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> dict:
    try:
        session = service.login(db, signing_key(), payload.username, payload.password)
    except ApiError as exc:
        _audit(
            request,
            "auth.login",
            "denied",
            error_code=exc.code,
            event_type="security_event",
            details={"username": payload.username, "reason": exc.code},
        )
        raise
    user = session["user"]
    _audit(
        request,
        "auth.login",
        "success",
        resource_type="user",
        resource_id=str(user["id"]),
        details={"username": payload.username},
    )
    return session


@auth_router.post("/internal/v1/auth/refresh", summary="刷新访问令牌")
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> dict:
    return service.refresh(db, signing_key(), payload.refresh_token)


@auth_router.get("/internal/v1/auth/me", summary="取当前用户、组织、角色与权限并集")
def current_user(
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(iam_principal),
) -> dict:
    user = service.get_user_by_id(db, principal.user_id)
    if user is None:
        raise ApiError("UNAUTHENTICATED", "账号不存在")
    expires_in = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60")) * 60
    return service.session_view(db, user, access_token=principal.raw_token, expires_in=expires_in)


@auth_router.get("/internal/v1/auth/public-keys", summary="获取验签公钥（供业务服务缓存）")
def public_keys() -> dict:
    key = signing_key()
    return {"keys": [{"kid": key.kid, "alg": "RS256", "public_key_pem": key.public_key_pem}]}


# --------------------------------------------------------------------------- 用户


@admin_router.get("/internal/v1/users", summary="分页查询用户")
def list_users(
    status: str | None = Query(default=None),
    organization_id: str | None = Query(default=None),
    role_code: str | None = Query(default=None),
    page: PageQuery = Depends(page_query),
    db: Session = Depends(get_db),
    _: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    return service.list_users(
        db,
        status=status,
        organization_id=organization_id,
        role_code=role_code,
        page=page.page,
        page_size=page.page_size,
    )


@admin_router.post("/internal/v1/users", status_code=201, summary="创建用户")
def create_user(
    payload: UserCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    user = service.create_user(
        db,
        username=payload.username,
        password=payload.password,
        display_name=payload.display_name,
        organization_id=payload.organization_id,
        role_codes=payload.role_codes,
        actor_id=principal.user_id,
    )
    _audit(
        request,
        "user.create",
        "success",
        actor=principal,
        resource_type="user",
        resource_id=user.id,
        details={"username": user.username, "role_codes": payload.role_codes},
    )
    return service.user_view(db, user)


@admin_router.get("/internal/v1/users/{user_id}", summary="用户详情")
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise ApiError("RESOURCE_NOT_FOUND", "用户不存在")
    return service.user_view(db, user)


@admin_router.patch("/internal/v1/users/{user_id}", summary="更新用户")
def update_user(
    user_id: str,
    payload: UserPatchRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise ApiError("RESOURCE_NOT_FOUND", "用户不存在")
    service.update_user(
        db,
        user,
        display_name=payload.display_name,
        organization_id=payload.organization_id,
        status=payload.status,
        new_password=payload.new_password,
        actor_id=principal.user_id,
    )
    _audit(
        request,
        "user.update",
        "success",
        actor=principal,
        resource_type="user",
        resource_id=user.id,
        details={
            "status": payload.status,
            "password_changed": payload.new_password is not None,
            "organization_changed": payload.organization_id is not None,
        },
    )
    return service.user_view(db, user)


@admin_router.get("/internal/v1/users/{user_id}/roles", summary="用户角色列表")
def list_user_roles(
    user_id: str,
    db: Session = Depends(get_db),
    _: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise ApiError("RESOURCE_NOT_FOUND", "用户不存在")
    return {"items": service.list_user_roles(db, user)}


@admin_router.post("/internal/v1/users/{user_id}/roles", status_code=201, summary="授予角色")
def assign_user_role(
    user_id: str,
    payload: RoleAssignRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise ApiError("RESOURCE_NOT_FOUND", "用户不存在")
    binding = service.assign_user_role(
        db, user, role_code=payload.role_code, expires_at=payload.expires_at, actor_id=principal.user_id
    )
    _audit(
        request,
        "user_role.assign",
        "success",
        actor=principal,
        resource_type="user",
        resource_id=user.id,
        details={"role_code": payload.role_code},
    )
    return binding


@admin_router.delete(
    "/internal/v1/users/{user_id}/roles/{role_code}", status_code=204, summary="撤销角色"
)
def revoke_user_role(
    user_id: str,
    role_code: str,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("iam:manage")),
) -> None:
    user = service.get_user_by_id(db, user_id)
    if user is None:
        raise ApiError("RESOURCE_NOT_FOUND", "用户不存在")
    service.revoke_user_role(db, user, role_code)
    _audit(
        request,
        "user_role.revoke",
        "success",
        actor=principal,
        resource_type="user",
        resource_id=user.id,
        details={"role_code": role_code},
    )


# --------------------------------------------------------------------------- 角色与权限


@admin_router.get("/internal/v1/roles", summary="角色列表")
def list_roles(
    db: Session = Depends(get_db), _: Principal = Depends(require_permission_local("iam:manage"))
) -> dict:
    return {"items": service.list_roles(db)}


@admin_router.post("/internal/v1/roles", status_code=201, summary="创建角色")
def create_role(
    payload: RoleCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    role = service.create_role(
        db, code=payload.code, name=payload.name, description=payload.description, actor_id=principal.user_id
    )
    _audit(
        request,
        "role.create",
        "success",
        actor=principal,
        resource_type="role",
        resource_id=role.id,
        details={"code": role.code},
    )
    return service.role_view(db, role)


@admin_router.put("/internal/v1/roles/{role_id}/permissions", summary="替换角色权限")
def replace_role_permissions(
    role_id: str,
    payload: RolePermissionsRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("iam:manage")),
) -> dict:
    role = db.scalars(select(Role).where(Role.id == role_id)).one_or_none()
    if role is None:
        raise ApiError("RESOURCE_NOT_FOUND", "角色不存在")
    updated = service.replace_role_permissions(
        db, role, payload.permission_codes, principal.user_id
    )
    _audit(
        request,
        "role.permissions.replace",
        "success",
        actor=principal,
        resource_type="role",
        resource_id=role.id,
        details={"permission_codes": payload.permission_codes},
    )
    return service.role_view(db, updated)


@admin_router.get("/internal/v1/permissions", summary="权限清单")
def list_permissions(
    db: Session = Depends(get_db), _: Principal = Depends(require_permission_local("iam:manage"))
) -> dict:
    return {"items": service.list_permissions(db)}


# --------------------------------------------------------------------------- 组织


@auth_router.get("/internal/v1/organizations", summary="组织列表")
def list_organizations(
    db: Session = Depends(get_db), _: Principal = Depends(iam_principal)
) -> dict:
    return {"items": service.list_organizations(db)}


@admin_router.post("/internal/v1/organizations", status_code=201, summary="创建组织")
def create_organization(
    payload: OrganizationCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    principal: Principal = Depends(require_permission_local("organization:manage")),
) -> dict:
    org = service.create_organization(
        db,
        code=payload.code,
        name=payload.name,
        parent_id=payload.parent_id,
        unit_type=payload.unit_type,
        sort_order=payload.sort_order,
        actor_id=principal.user_id,
    )
    _audit(
        request,
        "organization.create",
        "success",
        actor=principal,
        resource_type="organization",
        resource_id=org.id,
        details={"code": org.code},
    )
    return service.organization_view(org)


# --------------------------------------------------------------------------- 候选与二次校验


@auth_router.get("/internal/v1/candidates", summary="按目标角色筛选候选接收人")
def list_candidates(
    target_role: str = Query(min_length=1, max_length=32),
    source_organization_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Principal = Depends(iam_principal),
) -> dict:
    return {
        "items": service.list_candidates(
            db,
            target_role=target_role,
            source_organization_id=source_organization_id,
            limit=limit,
        )
    }


@auth_router.post("/internal/v1/users/resolve", summary="批量校验接收人")
def resolve_users(
    payload: ResolveUsersRequest,
    db: Session = Depends(get_db),
    _: Principal = Depends(iam_principal),
) -> dict:
    return {
        "items": service.resolve_users(
            db, user_ids=payload.user_ids, required_role=payload.required_role
        )
    }

