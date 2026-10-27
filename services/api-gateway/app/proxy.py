"""Gateway 的转发与鉴权封装。

职责分工（docs/architecture.md 第 5、10 节）：

- Gateway 负责「浏览器唯一入口」、请求 ID 透传和**入口级**鉴权（未认证直接 401，
  缺权限直接 403 并写安全审计）；
- 真正的业务授权仍由下游服务独立完成，Gateway 不是唯一授权点；
- 浏览器永远看不到内部服务地址。
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse

from nis_shared.auth import Principal, get_principal
from nis_shared.clients import _translate_error
from nis_shared.errors import ApiError

FORWARD_HEADERS = ("X-Role-Context", "Idempotency-Key")


def _iam_http(request: Request):  # noqa: ANN201
    client = getattr(request.app.state, "iam_http", None)
    if client is None:
        raise ApiError("SERVICE_UNAVAILABLE", "IAM 客户端未配置")
    return client


def authenticate(request: Request, *, public: bool, permission: str | None) -> Principal | None:
    if public:
        return None
    principal = get_principal(request)
    if permission and not principal.has(permission):
        _audit_denied(request, principal, permission)
        raise ApiError("FORBIDDEN", "没有执行该操作的权限", details={"permission": permission})
    return principal


def _audit_denied(request: Request, principal: Principal, permission: str) -> None:
    audit = getattr(request.app.state, "audit", None)
    if audit is None:
        return
    audit.write(
        event_type="security_event",
        action="gateway.permission.denied",
        result="denied",
        request_id=getattr(request.state, "request_id", ""),
        actor_user_id=principal.user_id,
        actor_role=principal.role_context,
        error_code="FORBIDDEN",
        source_ip=request.client.host if request.client else None,
        details={"permission": permission, "path": request.url.path},
    )


def forward(
    request: Request,
    method: str,
    path: str,
    *,
    public: bool = False,
    permission: str | None = None,
    json_body: Any = None,
    params: dict[str, Any] | None = None,
    status: int | None = None,
) -> tuple[int, Any]:
    """鉴权后转发到 IAM，返回 (状态码, 解析后的 JSON)。"""

    authenticate(request, public=public, permission=permission)
    headers = {name: request.headers[name] for name in FORWARD_HEADERS if name in request.headers}
    response: httpx.Response = _iam_http(request).request(
        method,
        path,
        token=_bearer(request),
        request_id=getattr(request.state, "request_id", None),
        json_body=json_body,
        params={k: v for k, v in (params or {}).items() if v is not None},
        headers=headers,
    )
    if response.status_code >= 500:
        raise ApiError("DEPENDENCY_FAILURE", details={"status": response.status_code})
    if response.status_code >= 400:
        raise _translate_error(response)
    if response.status_code == 204 or not response.content:
        return 204, None
    return status or response.status_code, response.json()


def forward_response(request: Request, method: str, path: str, **kwargs: Any) -> JSONResponse:
    code, payload = forward(request, method, path, **kwargs)
    return JSONResponse(payload, status_code=code)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" else None
