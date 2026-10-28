"""把服务需要的内部客户端挂到 ``app.state``。

所有服务都通过这里拿 ``app.state.iam`` / ``app.state.audit``，测试时替换成假实现即可，
不需要 monkeypatch 全局状态。
"""

from __future__ import annotations

from fastapi import FastAPI

from .clients import AuditClient, IamClient
from .config import ServiceSettings


def wire_clients(app: FastAPI, settings: ServiceSettings, *, with_iam: bool = True) -> None:
    app.state.audit = AuditClient(
        settings.downstream["audit-service"], service_name=settings.service
    )
    app.state.iam = (
        IamClient(settings.downstream["iam-service"]) if with_iam else None
    )
