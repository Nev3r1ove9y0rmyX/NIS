"""把服务需要的内部客户端挂到 ``app.state``。

所有服务都通过这里拿 ``app.state.iam`` / ``app.state.audit`` / ``app.state.recon`` 等，
测试时替换成假实现即可，不需要 monkeypatch 全局状态。
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
from .config import ServiceSettings


def wire_clients(
    app: FastAPI,
    settings: ServiceSettings,
    *,
    with_iam: bool = True,
    with_recon: bool = False,
    with_analysis: bool = False,
    with_execution: bool = False,
    with_decision: bool = False,
) -> None:
    app.state.audit = AuditClient(
        settings.downstream["audit-service"], service_name=settings.service
    )
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
