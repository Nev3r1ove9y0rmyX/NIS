"""业务服务侧的认证与授权依赖。

每个受保护接口都走同一条链路（docs/rbac.md 第 6 节）：

1. 取 ``Authorization: Bearer``；
2. 用 IAM 公钥**本地验签**（业务服务不信任「Gateway 传来的用户头」）；
3. 每请求向 IAM 取当前身份与权限并集（改权限后立即生效，不读 JWT 里的旧权限）；
4. 校验 ``X-Role-Context``：多角色用户必填且必须属于其有效角色（决策 D-03）；
5. 交给 :func:`require_permission` 判断权限代码，资源范围由各业务接口自行继续校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import jwt as pyjwt
from fastapi import Request

from .errors import ApiError
from .jwt_tokens import TokenError, decode_token

ROLE_CONTEXT_HEADER = "X-Role-Context"


@dataclass(frozen=True)
class Principal:
    user_id: str
    username: str
    display_name: str
    roles: tuple[str, ...]
    permissions: frozenset[str]
    organization: dict[str, Any] = field(default_factory=dict)
    role_context: str | None = None
    raw_token: str = ""

    @property
    def organization_id(self) -> str | None:
        return self.organization.get("id")

    def has(self, permission: str) -> bool:
        return permission in self.permissions


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError("UNAUTHENTICATED", "缺少 Bearer 令牌")
    return token.strip()


def _kid_of(token: str) -> str | None:
    try:
        return pyjwt.get_unverified_header(token).get("kid")
    except pyjwt.PyJWTError:
        return None


def _header_role(request: Request) -> str | None:
    return (request.headers.get(ROLE_CONTEXT_HEADER) or "").strip() or None


def resolve_role_context(header_value: str | None, roles: tuple[str, ...]) -> str | None:
    """多角色必填、单角色可省略；不匹配返回 403（决策 D-03）。"""

    context = (header_value or "").strip() or None
    if context is None:
        if len(roles) > 1:
            raise ApiError(
                "FORBIDDEN",
                "该账号拥有多个角色，请求必须携带 X-Role-Context",
                details={"roles": list(roles)},
            )
        return roles[0] if roles else None
    if context not in roles:
        raise ApiError(
            "FORBIDDEN",
            "X-Role-Context 不属于该用户的有效角色",
            details={"role_context": context, "roles": list(roles)},
        )
    return context


def get_principal(request: Request) -> Principal:
    """FastAPI 依赖：认证 + 角色上下文 + 权限并集。"""

    app = request.app
    iam = getattr(app.state, "iam", None)
    if iam is None:
        raise ApiError("SERVICE_UNAVAILABLE", "IAM 客户端未配置")

    token = _bearer(request)
    public_key = iam.keys.get(_kid_of(token))
    try:
        payload = decode_token(token, public_key)
    except TokenError as exc:
        _audit(request, "auth.token.invalid", "denied", error_code="UNAUTHENTICATED", details={"reason": str(exc)})
        raise ApiError("UNAUTHENTICATED", "令牌无效或已过期") from exc

    session = iam.me(token, getattr(request.state, "request_id", None), role_context=_header_role(request))
    user = session.get("user") or {}
    roles = tuple(user.get("roles") or payload.roles)
    header_value = request.headers.get(ROLE_CONTEXT_HEADER)
    try:
        role_context = resolve_role_context(header_value, roles)
    except ApiError as exc:
        _audit(
            request,
            "auth.role_context.denied",
            "denied",
            actor_user_id=user.get("id"),
            resource_type="user",
            resource_id=user.get("id"),
            error_code=exc.code,
            details=exc.details,
        )
        raise

    principal = Principal(
        user_id=str(user.get("id") or payload.user_id),
        username=str(user.get("username") or ""),
        display_name=str(user.get("display_name") or ""),
        roles=roles,
        permissions=frozenset(user.get("permissions") or ()),
        organization=user.get("organization") or {},
        role_context=role_context,
        raw_token=token,
    )
    request.state.principal = principal
    return principal


def require_permission(code: str) -> Callable[[Request], Principal]:
    """权限代码依赖工厂：``Depends(require_permission("iam:manage"))``。"""

    def _dependency(request: Request) -> Principal:
        principal = get_principal(request)
        if not principal.has(code):
            _audit(
                request,
                "auth.permission.denied",
                "denied",
                actor_user_id=principal.user_id,
                actor_role=principal.role_context,
                error_code="FORBIDDEN",
                details={"permission": code, "path": request.url.path},
            )
            raise ApiError("FORBIDDEN", "没有执行该操作的权限", details={"permission": code})
        return principal

    _dependency.__name__ = f"require_permission_{code.replace(':', '_')}"
    return _dependency


def current_principal(request: Request) -> Principal:
    """已认证即可，不要求具体权限代码。"""

    principal = getattr(request.state, "principal", None)
    return principal if principal is not None else get_principal(request)


def _audit(
    request: Request,
    action: str,
    result: str,
    *,
    actor_user_id: str | None = None,
    actor_role: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    error_code: str | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """安全审计：越权、无效令牌、角色上下文不符都要留痕（FR-AUDIT-001）。"""

    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    audit.write(
        event_type="security_event",
        action=action,
        result=result,
        request_id=getattr(request.state, "request_id", ""),
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        resource_type=resource_type,
        resource_id=resource_id,
        error_code=error_code,
        source_ip=request.client.host if request.client else None,
        details=details,
    )


def audit_denied(request: Request, action: str, *, permission: str | None = None) -> None:
    """给业务接口复用：资源范围不符时写一条 denied。"""

    principal: Principal | None = getattr(request.state, "principal", None)
    _audit(
        request,
        action,
        "denied",
        actor_user_id=principal.user_id if principal else None,
        actor_role=principal.role_context if principal else None,
        error_code="FORBIDDEN",
        details={"permission": permission} if permission else None,
    )
