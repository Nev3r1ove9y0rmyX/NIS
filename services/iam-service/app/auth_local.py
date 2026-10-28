"""IAM 的签名密钥与本地验签依赖。

IAM 是唯一持有私钥的服务（docs/architecture.md 第 10 节）。它的 ``/auth/me`` 不能像其他
服务那样回调 IAM，所以这里提供「本地验签 + 查库」的依赖，链路与业务服务保持同构。
"""

from __future__ import annotations

from typing import Iterator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from nis_shared.auth import Principal, resolve_role_context
from nis_shared.errors import ApiError
from nis_shared.jwt_tokens import SigningKey, TokenError, decode_token, load_signing_key

from app import service

_signing_key: SigningKey | None = None


def signing_key() -> SigningKey:
    global _signing_key
    if _signing_key is None:
        _signing_key = load_signing_key()
    return _signing_key


def reset_signing_key() -> None:
    """测试用：强制重新生成/加载密钥。"""

    global _signing_key
    _signing_key = None


def get_db(request: Request) -> Iterator[Session]:
    database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    finally:
        session.close()


def _bearer(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise ApiError("UNAUTHENTICATED", "缺少 Bearer 令牌")
    return token.strip()


def iam_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    """本地验签 + 取用户与权限并集；供 IAM 自己的接口使用。"""

    token = _bearer(request)
    try:
        payload = decode_token(token, signing_key().public_key_pem)
    except TokenError as exc:
        raise ApiError("UNAUTHENTICATED", "令牌无效或已过期") from exc

    user = service.get_user_by_id(db, payload.user_id)
    if user is None or not user.is_active:
        raise ApiError("UNAUTHENTICATED", "账号不存在或已停用")

    roles = service.roles_of(db, user.id)
    role_context = resolve_role_context(request.headers.get("X-Role-Context"), roles)
    principal = Principal(
        user_id=user.id,
        username=user.username,
        display_name=user.display_name,
        roles=roles,
        permissions=frozenset(service.permissions_of(db, user.id)),
        organization={"id": user.organization_id},
        role_context=role_context,
        raw_token=token,
    )
    request.state.principal = principal
    return principal


def require_permission_local(code: str):  # noqa: ANN201
    """IAM 自己的权限依赖：本地验签 + 本地权限并集，不回调自身。"""

    def _dependency(
        request: Request, principal: Principal = Depends(iam_principal)
    ) -> Principal:
        if principal.has(code):
            return principal
        audit = getattr(request.app.state, "audit", None)
        if audit is not None:
            audit.write(
                event_type="security_event",
                action="auth.permission.denied",
                result="denied",
                request_id=getattr(request.state, "request_id", ""),
                actor_user_id=principal.user_id,
                actor_role=principal.role_context,
                error_code="FORBIDDEN",
                source_ip=request.client.host if request.client else None,
                details={"permission": code, "path": request.url.path},
            )
        raise ApiError("FORBIDDEN", "没有执行该操作的权限", details={"permission": code})

    _dependency.__name__ = f"require_permission_local_{code.replace(':', '_')}"
    return _dependency

