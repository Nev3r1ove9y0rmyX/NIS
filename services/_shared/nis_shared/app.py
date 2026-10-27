"""所有服务共用的 FastAPI 应用工厂。

一次装配到位：请求 ID 中间件、统一错误体、结构化访问日志、``/health/live`` 与
``/health/ready``（契约见各服务 OpenAPI 的 ``Health`` schema）。
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable, Sequence
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import ServiceSettings
from .db import Database
from .errors import ApiError
from .logging import configure_logging

REQUEST_ID_HEADER = "X-Request-ID"
ROLE_CONTEXT_HEADER = "X-Role-Context"


def utc_timestamp() -> str:
    """契约要求 ISO 8601 UTC，例如 ``2026-10-16T08:30:00Z``。"""

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or str(uuid.uuid4())


def _error_body(
    code: str, message: str, request_id: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id}
    if details:
        body["details"] = details
    return body


def build_health_router(
    service: str,
    database: Database | None,
    readiness_probe: Callable[[], dict[str, str]] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["健康检查"])

    def _payload(status: str, dependencies: dict[str, str]) -> dict[str, Any]:
        return {
            "status": status,
            "service": service,
            "checked_at": utc_timestamp(),
            "dependencies": dependencies,
        }

    @router.get("/health/live", summary="存活检查")
    def live() -> dict[str, Any]:
        """进程能响应即存活，不检查下游（soa-deployment 第 6 节）。"""

        return _payload("ok", {})

    @router.get("/health/ready", summary="就绪检查（含数据库）")
    def ready(request: Request) -> JSONResponse:
        dependencies: dict[str, str] = {}
        if database is not None:
            dependencies["database"] = "ok" if database.ping() else "down"
        if readiness_probe is not None:
            dependencies.update(readiness_probe())
        healthy = all(value == "ok" for value in dependencies.values())
        if healthy:
            return JSONResponse(_payload("ok", dependencies), status_code=200)
        return JSONResponse(
            _error_body(
                "SERVICE_UNAVAILABLE",
                f"{service} 未就绪：" + ", ".join(f"{k}={v}" for k, v in dependencies.items()),
                _request_id(request),
                {"dependencies": dependencies},
            ),
            status_code=503,
        )

    return router


def create_service_app(
    settings: ServiceSettings,
    *,
    database: Database | None = None,
    routers: Sequence[APIRouter] = (),
    readiness_probe: Callable[[], dict[str, str]] | None = None,
    title: str | None = None,
    version: str = "0.1.0",
) -> FastAPI:
    """为单个服务装配 FastAPI 应用。"""

    logger = configure_logging(settings.service, settings.log_level)
    app = FastAPI(title=title or f"NIS {settings.service}", version=version)
    app.state.settings = settings
    app.state.database = database
    app.state.logger = logger

    @app.middleware("http")
    async def request_context(request: Request, call_next):  # type: ignore[no-untyped-def]
        incoming = request.headers.get(REQUEST_ID_HEADER)
        request.state.request_id = incoming or str(uuid.uuid4())
        request.state.role_context = request.headers.get(ROLE_CONTEXT_HEADER)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        response.headers[REQUEST_ID_HEADER] = request.state.request_id
        logger.info(
            "request",
            extra={
                "request_id": request.state.request_id,
                "event": "http.access",
                "action": f"{request.method} {request.url.path}",
                "result": str(response.status_code),
                "duration_ms": duration_ms,
            },
        )
        return response

    @app.exception_handler(ApiError)
    async def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            _error_body(exc.code, exc.message, _request_id(request), exc.details),
            status_code=exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        issues = [
            {
                "field": ".".join(
                    str(part)
                    for part in err.get("loc", ())
                    # 去掉 body/query/path/header 这类位置前缀，前端按字段名回显
                    if part not in ("body", "query", "path", "header", "cookie")
                ),
                "reason": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            _error_body(
                "VALIDATION_ERROR",
                "字段校验错误",
                _request_id(request),
                {"issues": issues},
            ),
            status_code=422,
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "RESOURCE_NOT_FOUND",
            405: "INVALID_REQUEST",
            409: "WORKFLOW_CONFLICT",
            429: "RATE_LIMITED",
        }.get(exc.status_code, "INVALID_REQUEST")
        message = exc.detail if isinstance(exc.detail, str) else "请求无法处理"
        return JSONResponse(
            _error_body(code, message, _request_id(request)), status_code=exc.status_code
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 记录堆栈到服务端日志，但绝不返回给客户端（NFR-SEC-003）。
        logging.getLogger(settings.service).exception(
            "unhandled error", extra={"request_id": _request_id(request)}
        )
        return JSONResponse(
            _error_body("INTERNAL_ERROR", "服务内部错误", _request_id(request)),
            status_code=500,
        )

    app.include_router(build_health_router(settings.service, database, readiness_probe))
    for router in routers:
        app.include_router(router)
    return app
