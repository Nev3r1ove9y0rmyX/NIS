"""把服务需要的内部客户端挂到 ``app.state``。

所有服务都通过这里拿 ``app.state.iam`` / ``app.state.audit`` / ``app.state.recon`` 等，
测试时替换成假实现即可，不需要 monkeypatch 全局状态。

``settings.downstream`` 不包含服务自己，所以审计服务本身用 ``with_audit=False``（它不审计自己）。
"""

from __future__ import annotations

from fastapi import FastAPI

from .clients import (
    AnalysisClient,
    AuditClient,
    DecisionClient,
    ExecutionClient,
    IamClient,
    ReconClient,
)
from .config import SERVICE_PORT, ServiceSettings


def wire_clients(
    app: FastAPI,
    settings: ServiceSettings,
    *,
    with_iam: bool = True,
    with_audit: bool = True,
    with_recon: bool = False,
    with_analysis: bool = False,
    with_execution: bool = False,
    with_decision: bool = False,
) -> None:
    if with_audit:
        audit_url = settings.downstream.get(
            "audit-service", f"http://127.0.0.1:{SERVICE_PORT['audit-service']}"
        )
        app.state.audit = AuditClient(audit_url, service_name=settings.service)
    else:
        app.state.audit = None
    app.state.iam = IamClient(settings.downstream["iam-service"]) if with_iam else None
    app.state.recon = (
        ReconClient(settings.downstream["recon-service"]) if with_recon else None
    )
    app.state.analysis = (
        AnalysisClient(settings.downstream["analysis-service"]) if with_analysis else None
    )
    app.state.execution = (
        ExecutionClient(settings.downstream["execution-service"]) if with_execution else None
    )
    app.state.decision = (
        DecisionClient(settings.downstream["decision-service"]) if with_decision else None
    )
