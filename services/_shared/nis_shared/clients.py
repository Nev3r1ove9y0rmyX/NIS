"""内部服务客户端。

统一超时与错误映射（docs/service-contracts.md 第 4 节）：连接 1 秒、总 3 秒；
下游失败映射成稳定的 ``DEPENDENCY_FAILURE`` / ``DEPENDENCY_TIMEOUT``，不把内部地址
或原始堆栈返回给浏览器。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from .errors import ApiError

CONNECT_TIMEOUT = float(__import__("os").environ.get("HTTP_CONNECT_TIMEOUT", "1"))
TOTAL_TIMEOUT = float(__import__("os").environ.get("HTTP_TOTAL_TIMEOUT", "3"))

logger = logging.getLogger("nis.clients")


class InternalClient:
    """一次构造、多处复用；测试可注入 ``httpx.MockTransport`` 或 ASGI transport。"""

    def __init__(
        self,
        base_url: str,
        *,
        transport: httpx.BaseTransport | None = None,
        service_name: str | None = None,
        service_token: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.service_name = service_name
        self._service_token = service_token
        timeout = httpx.Timeout(TOTAL_TIMEOUT, connect=CONNECT_TIMEOUT)
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport)

    def close(self) -> None:
        self._client.close()

    def _headers(self, token: str | None, request_id: str | None, extra: dict[str, str] | None) -> dict[str, str]:
        headers: dict[str, str] = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if request_id:
            headers["X-Request-ID"] = request_id
        if self.service_name:
            headers["X-Service-Name"] = self.service_name
        if self._service_token:
            headers["X-Service-Token"] = self._service_token
        if extra:
            headers.update(extra)
        return headers

    def request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        request_id: str | None = None,
        json_body: Any = None,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method,
                path,
                json=json_body,
                params=params,
                headers=self._headers(token, request_id, headers),
            )
        except httpx.TimeoutException as exc:
            raise ApiError("DEPENDENCY_TIMEOUT", details={"target": self.base_url}) from exc
        except httpx.HTTPError as exc:
            raise ApiError("DEPENDENCY_FAILURE", details={"target": self.base_url}) from exc
        return response

    def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.request(method, path, **kwargs)
        if response.status_code >= 500:
            raise ApiError("DEPENDENCY_FAILURE", details={"status": response.status_code})
        if response.status_code >= 400:
            raise _translate_error(response)
        if response.status_code == 204 or not response.content:
            return None
        return response.json()


def _translate_error(response: httpx.Response) -> ApiError:
    """把下游错误体透传成同样的稳定错误码，未知情况退化为 400/403。"""

    try:
        payload = response.json()
    except ValueError:
        payload = {}
    code = payload.get("code")
    message = payload.get("message")
    from .errors import ERROR_CATALOG  # 循环依赖最小化：仅在出错路径导入

    if code not in ERROR_CATALOG:
        code = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            409: "WORKFLOW_CONFLICT",
            422: "VALIDATION_ERROR",
            500: "DEPENDENCY_FAILURE",
            502: "DEPENDENCY_FAILURE",
            503: "SERVICE_UNAVAILABLE",
            504: "DEPENDENCY_TIMEOUT",
        }.get(response.status_code, "INVALID_REQUEST")
    return ApiError(code, message, details=payload.get("details") or {}, status_code=response.status_code)


class PublicKeyCache:
    """IAM 公钥缓存：按 ``kid`` 命中，未知 ``kid`` 时强制刷新一次。"""

    def __init__(self, iam: InternalClient, ttl_seconds: int = 300) -> None:
        self._iam = iam
        self._ttl = ttl_seconds
        self._keys: dict[str, str] = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def get(self, kid: str | None = None) -> str:
        with self._lock:
            expired = (time.monotonic() - self._fetched_at) > self._ttl
            if not self._keys or expired or (kid and kid not in self._keys):
                self._refresh()
        if kid and kid in self._keys:
            return self._keys[kid]
        # 没有 kid 或缓存未命中但已刷新过：单密钥部署时直接用唯一公钥
        if len(self._keys) == 1:
            return next(iter(self._keys.values()))
        raise ApiError("UNAUTHENTICATED", "无法确定令牌签名公钥")

    def _refresh(self) -> None:
        payload = self._iam.request_json("GET", "/internal/v1/auth/public-keys")
        keys = {item["kid"]: item["public_key_pem"] for item in payload.get("keys", [])}
        if not keys:
            raise ApiError("DEPENDENCY_FAILURE", "IAM 未返回验签公钥")
        self._keys = keys
        self._fetched_at = time.monotonic()
        logger.info("public keys refreshed", extra={"event": "iam.public_keys", "result": str(len(keys))})


class IamClient:
    """IAM 的业务侧封装：当前身份与候选接收人。"""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._http = InternalClient(base_url, transport=transport, service_name="nis-service")
        self.keys = PublicKeyCache(self._http)

    def me(
        self, token: str, request_id: str | None = None, role_context: str | None = None
    ) -> dict[str, Any]:
        """取当前身份；多角色用户必须把 ``X-Role-Context`` 一起转发给 IAM。"""

        extra = {"X-Role-Context": role_context} if role_context else None
        return self._http.request_json(
            "GET", "/internal/v1/auth/me", token=token, request_id=request_id, headers=extra
        )

    def candidates(self, **params: Any) -> list[dict[str, Any]]:
        payload = self._http.request_json("GET", "/internal/v1/candidates", params=params)
        return payload.get("items", [])

    def resolve(
        self,
        user_ids: list[str],
        required_role: str,
        *,
        token: str | None = None,
        request_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """提交时二次校验接收人；必须带调用者令牌，IAM 侧会再验一次身份。"""

        payload = self._http.request_json(
            "POST",
            "/internal/v1/users/resolve",
            json_body={"user_ids": user_ids, "required_role": required_role},
            token=token,
            request_id=request_id,
        )
        return payload.get("items", [])


class ReconClient:
    """分析服务读取侦察数据的唯一入口：必须走授权接口，不直连 nis_recon。"""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._http = InternalClient(base_url, transport=transport, service_name="nis-service")

    def authorized_view(
        self,
        record_id: str,
        *,
        requester_id: str,
        purpose: str,
        token: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._http.request_json(
            "GET",
            f"/internal/v1/recon-records/{record_id}/authorized-view",
            token=token,
            request_id=request_id,
            params={"requester_user_id": requester_id, "purpose": purpose},
        )

    def analysis_state(
        self,
        record_id: str,
        *,
        analyst_id: str,
        assignment_status: str,
        reject_reason: str | None,
        token: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._http.request_json(
            "POST",
            f"/internal/v1/recon-records/{record_id}/analysis-state",
            token=token,
            request_id=request_id,
            json_body={
                "analyst_id": analyst_id,
                "assignment_status": assignment_status,
                "reject_reason": reject_reason,
            },
        )


class AnalysisClient:
    """决策服务读取分析报告的唯一入口：必须走授权接口。"""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._http = InternalClient(base_url, transport=transport, service_name="decision-service")

    def authorized_view(
        self,
        report_id: str,
        *,
        requester_id: str,
        purpose: str,
        token: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._http.request_json(
            "GET",
            f"/internal/v1/analysis-reports/{report_id}/authorized-view",
            token=token,
            request_id=request_id,
            params={"requester_user_id": requester_id, "purpose": purpose},
        )

    def decision_state(
        self,
        report_id: str,
        *,
        state: str,
        command_id: str | None,
        reason: str | None,
        token: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._http.request_json(
            "POST",
            f"/internal/v1/analysis-reports/{report_id}/decision-state",
            token=token,
            request_id=request_id,
            json_body={"state": state, "command_id": command_id, "reason": reason},
        )


class ExecutionClient:
    """决策服务创建个人执行分配的唯一入口（architecture §7：DEC -> EXE）。"""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._http = InternalClient(base_url, transport=transport, service_name="decision-service")

    def create_assignments(
        self, payload: dict[str, Any], *, token: str, request_id: str | None = None
    ) -> list[dict[str, Any]]:
        body = self._http.request_json(
            "POST",
            "/internal/v1/assignments",
            json_body=payload,
            token=token,
            request_id=request_id,
        )
        return body.get("items", [])


class DecisionClient:
    """执行服务回写个人状态与读取总体状态的唯一入口。"""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self._http = InternalClient(base_url, transport=transport, service_name="execution-service")

    def apply_assignment_state(
        self,
        command_id: str,
        *,
        assignment_id: str,
        executor_id: str,
        status: str,
        token: str,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        return self._http.request_json(
            "POST",
            f"/internal/v1/commands/{command_id}/assignment-state",
            json_body={
                "assignment_id": assignment_id,
                "executor_id": executor_id,
                "status": status,
            },
            token=token,
            request_id=request_id,
        )

    def get_status(
        self, command_id: str, *, token: str, request_id: str | None = None
    ) -> dict[str, Any]:
        return self._http.request_json(
            "GET",
            f"/internal/v1/commands/{command_id}/status",
            token=token,
            request_id=request_id,
        )


class AuditClient:
    """写审计事件到 audit-service；失败只记日志，不影响业务结果，但会显式告警。"""

    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None, service_name: str = "nis-service") -> None:
        self._http = InternalClient(base_url, transport=transport, service_name=service_name)

    def write(
        self,
        *,
        event_type: str,
        action: str,
        result: str,
        request_id: str,
        actor_user_id: str | None = None,
        actor_role: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        error_code: str | None = None,
        source_ip: str | None = None,
        service: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> bool:
        body = {
            "request_id": request_id,
            "event_type": event_type,
            "action": action,
            "result": result,
            # 事件必须带产生它的服务名；未显式传入时用本服务的身份
            "service": service or self._http.service_name or "unknown-service",
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "error_code": error_code,
            "source_ip": source_ip,
            "details": details or {},
        }
        try:
            response = self._http.request(
                "POST",
                "/internal/v1/audit-events",
                json_body=body,
                request_id=request_id,
                headers={"Idempotency-Key": f"{request_id}:{action}"},
            )
        except ApiError as exc:
            logger.error(
                "audit write failed",
                extra={"request_id": request_id, "event": "audit.write", "result": exc.code},
            )
            return False
        if response.status_code >= 400:
            logger.error(
                "audit write rejected",
                extra={"request_id": request_id, "event": "audit.write", "result": str(response.status_code)},
            )
            return False
        return True
