"""结构化日志。

每行一个 JSON 对象，始终带 ``request_id``，便于按 ``X-Request-ID`` 还原调用链
（``docs/service-contracts.md`` 第 4 节）。禁止打印密码、Token、连接串与敏感正文。
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

#: 日志里一旦出现这些键名就会被替换成占位符，避免误写敏感值。
_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "new_password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "secret",
    "jwt_private_key",
    "mysql_root_password",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scrub(value: object) -> object:
    if isinstance(value, dict):
        return {
            k: ("***" if str(k).lower() in _SENSITIVE_KEYS else _scrub(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": utc_iso(),
            "level": record.levelname,
            "service": self.service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "event", "actor_id", "resource", "action", "result", "duration_ms"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(_scrub(payload), ensure_ascii=False)


def configure_logging(service: str, level: str = "INFO") -> logging.Logger:
    """配置根日志；重复调用不会叠加 handler。"""

    root = logging.getLogger()
    root.setLevel(level.upper())
    for handler in list(root.handlers):
        if getattr(handler, "_nis_json", False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    handler._nis_json = True  # type: ignore[attr-defined]
    root.addHandler(handler)
    # uvicorn 自带 handler 会输出非 JSON，这里只保留路径级别报错
    logging.getLogger("uvicorn.access").disabled = True
    return logging.getLogger(service)
