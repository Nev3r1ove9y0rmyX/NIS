"""统一错误体。

格式固定为 ``{code, message, request_id, details}``（``docs/service-contracts.md`` 第 3 节）。
任何响应都不得包含堆栈、SQL、密钥或内部路径。
"""

from __future__ import annotations

from typing import Any

#: 稳定错误码表（HTTP 状态码, 错误码）→ 默认中文提示。
ERROR_CATALOG: dict[str, tuple[int, str]] = {
    "INVALID_REQUEST": (400, "请求结构或业务参数错误"),
    "UNAUTHENTICATED": (401, "未登录、Token 无效或已过期"),
    "FORBIDDEN": (403, "没有执行该操作的权限"),
    "RESOURCE_NOT_FOUND": (404, "资源不存在"),
    "VERSION_CONFLICT": (409, "数据已被他人修改，请刷新后重试"),
    "WORKFLOW_CONFLICT": (409, "当前状态不允许该操作"),
    "DUPLICATE_OPERATION": (409, "重复操作且无法安全返回原结果"),
    "IDEMPOTENCY_CONFLICT": (409, "同一幂等键对应的请求体不一致"),
    "ACCOUNT_LOCKED": (423, "连续登录失败，账号已被临时锁定"),
    "RATE_LIMITED": (429, "请求过于频繁，请稍后再试"),
    "VALIDATION_ERROR": (422, "字段校验错误"),
    "DEPENDENCY_FAILURE": (502, "下游服务失败"),
    "SERVICE_UNAVAILABLE": (503, "服务未就绪或暂不可用"),
    "DEPENDENCY_TIMEOUT": (504, "下游服务超时"),
    "INTERNAL_ERROR": (500, "服务内部错误"),
}


class ApiError(Exception):
    """业务异常：抛出即被统一处理器转成契约规定的错误体。"""

    def __init__(
        self,
        code: str,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        if code not in ERROR_CATALOG:
            raise ValueError(f"未登记的错误码：{code}")
        default_status, default_message = ERROR_CATALOG[code]
        self.code = code
        self.message = message or default_message
        self.details = details or {}
        self.status_code = status_code or default_status
        super().__init__(self.message)
