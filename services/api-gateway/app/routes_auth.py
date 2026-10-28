"""Gateway 公共路由：认证、组织、候选接收人（/api/v1）。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from app.payloads import LoginRequest, RefreshRequest
from app.proxy import forward
from nis_shared.auth import get_principal

router = APIRouter(prefix="/api/v1", tags=["认证与组织"])


def organization_ref(org: dict | None) -> dict:
    org = org or {}
    return {"id": org.get("id"), "code": org.get("code"), "name": org.get("name")}


def current_user_view(session: dict) -> dict:
    user = session.get("user") or {}
    return {
        "id": user.get("id"),
        "username": user.get("username"),
        "display_name": user.get("display_name"),
        "organization": organization_ref(user.get("organization")),
        "roles": user.get("roles") or [],
        "permissions": user.get("permissions") or [],
    }


@router.post("/auth/login", summary="登录")
def login(payload: LoginRequest, request: Request) -> JSONResponse:
    _, session = forward(
        request, "POST", "/internal/v1/auth/login", public=True, json_body=payload.model_dump()
    )
    token = session["token"]
    return JSONResponse(
        {
            "access_token": token["access_token"],
            "refresh_token": token["refresh_token"],
            "token_type": token["token_type"],
            "expires_in": token["expires_in"],
            "user": current_user_view(session),
        },
        status_code=200,
    )


@router.post("/auth/refresh", summary="刷新令牌")
def refresh_token(payload: RefreshRequest, request: Request) -> JSONResponse:
    code, tokens = forward(
        request, "POST", "/internal/v1/auth/refresh", public=True, json_body=payload.model_dump()
    )
    return JSONResponse(tokens, status_code=code)


@router.post("/auth/logout", status_code=204, summary="退出登录")
def logout(request: Request) -> Response:
    principal = get_principal(request)
    audit = getattr(request.app.state, "audit", None)
    if audit is not None:
        audit.write(
            event_type="user_operation",
            action="auth.logout",
            result="success",
            request_id=getattr(request.state, "request_id", ""),
            actor_user_id=principal.user_id,
            actor_role=principal.role_context,
            source_ip=request.client.host if request.client else None,
        )
    # 无状态退出：客户端丢弃令牌；令牌仍受 TTL 与每请求账号状态检查约束。
    # 204 必须没有响应体：JSONResponse(None) 会写出字面量 "null"，uvicorn 抛
    # RuntimeError("Response content longer than Content-Length")，浏览器侧表现为请求失败。
    return Response(status_code=204)


@router.get("/auth/me", summary="当前身份")
def get_current_user(request: Request) -> JSONResponse:
    _, session = forward(request, "GET", "/internal/v1/auth/me")
    return JSONResponse(current_user_view(session), status_code=200)


@router.get("/organizations", summary="组织列表")
def list_organizations(request: Request) -> JSONResponse:
    _, payload = forward(request, "GET", "/internal/v1/organizations")
    items = [
        {
            **organization_ref(org),
            "parent_id": org.get("parent_id"),
            "unit_type": org.get("unit_type"),
            "is_active": org.get("is_active"),
        }
        for org in payload.get("items", [])
    ]
    return JSONResponse({"items": items}, status_code=200)


@router.get("/candidates", summary="候选接收人")
def list_candidates(
    request: Request,
    target_role: str = Query(min_length=1, max_length=32),
    source_record_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    # source_record_id 的组织推导依赖侦察服务（Issue #9 接入），当前按全组织范围返回。
    _, payload = forward(
        request,
        "GET",
        "/internal/v1/candidates",
        params={"target_role": target_role, "limit": min(page * page_size, 200)},
    )
    items = [
        {
            "user_id": item.get("user_id"),
            "display_name": item.get("display_name"),
            "role_code": item.get("role_code"),
            "organization": {
                "id": item.get("organization_id"),
                "code": item.get("organization_code"),
                "name": item.get("organization_name"),
            },
        }
        for item in payload.get("items", [])
    ]
    start = (page - 1) * page_size
    return JSONResponse(
        {
            "items": items[start : start + page_size],
            "page": page,
            "page_size": page_size,
            "total": len(items),
        },
        status_code=200,
    )
