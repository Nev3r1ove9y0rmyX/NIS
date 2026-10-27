"""Gateway 业务路由：侦察记录与分析报告（/api/v1）。

三条硬规则：

1. **身份只从令牌来**：``owner_id`` / ``author_id`` / ``viewer_user_id`` 一律由 Gateway 注入，
   浏览器传什么都不认，避免冒充他人提交或窥探他人数据；
2. **入口鉴权 + 下游二次鉴权**：这里判权限代码，下游服务判资源范围与状态；
3. **幂等键与角色上下文原样透传**：重试沿用同一把键、多角色用户必须带角色上下文。
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.proxy import forward as _forward_iam
from nis_shared.auth import Principal, get_principal
from nis_shared.errors import ApiError

router = APIRouter(prefix="/api/v1", tags=["业务"])

SOURCE_TYPES = "^(osint|sensor|report|document|other)$"
CREDIBILITY = "^(high|medium|low|unverified)$"
PRIORITY = "^(normal|urgent)$"
RISK = "^(low|medium|high)$"


class EvidenceInput(BaseModel):
    file_name: str = Field(max_length=255)
    media_type: str = Field(max_length=127)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")


class ReconRecordWrite(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    source_type: str = Field(pattern=SOURCE_TYPES)
    source_ref: str | None = Field(default=None, max_length=500)
    content: str = Field(min_length=10, max_length=8000)
    credibility: str = Field(pattern=CREDIBILITY)
    priority: str = Field(pattern=PRIORITY)
    evidence: list[EvidenceInput] = Field(default_factory=list)


class ReconRecordPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    source_type: str | None = Field(default=None, pattern=SOURCE_TYPES)
    source_ref: str | None = Field(default=None, max_length=500)
    content: str | None = Field(default=None, min_length=10, max_length=8000)
    credibility: str | None = Field(default=None, pattern=CREDIBILITY)
    priority: str | None = Field(default=None, pattern=PRIORITY)


class ReconSubmitRequest(BaseModel):
    expected_version: int = Field(ge=1)
    analyst_ids: list[str] = Field(min_length=1)
    priority: str | None = Field(default=None, pattern=PRIORITY)


class AnalysisReportWrite(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    recon_record_ids: list[str] = Field(min_length=1)
    key_findings: str = Field(min_length=10, max_length=8000)
    relations: str | None = Field(default=None, max_length=8000)
    risk_level: str = Field(pattern=RISK)
    recommended_actions: str = Field(min_length=2, max_length=4000)
    priority: str = Field(pattern=PRIORITY)


class AnalysisReportPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    key_findings: str | None = Field(default=None, min_length=10, max_length=8000)
    relations: str | None = Field(default=None, max_length=8000)
    risk_level: str | None = Field(default=None, pattern=RISK)
    recommended_actions: str | None = Field(default=None, min_length=2, max_length=4000)
    priority: str | None = Field(default=None, pattern=PRIORITY)


class AnalysisReportSubmitRequest(BaseModel):
    expected_version: int = Field(ge=1)
    decision_maker_ids: list[str] = Field(min_length=1)
    #: 契约未列该字段，但「AI 内容必须逐条确认后才能提交」是硬要求（FR-ANALYSIS-003）。
    #: 这里按 fail-closed 处理：不显式声明已确认就不放行。
    ai_content_confirmed: bool = False


def _fwd(request: Request, method: str, path: str, **kwargs):  # noqa: ANN003, ANN201
    """侦察与分析的转发入口：按路径选择上游服务。"""

    upstream = "recon" if path.startswith("/internal/v1/recon-records") else "analysis"
    return _forward_iam(request, method, path, upstream=upstream, **kwargs)


def _principal(request: Request, permission: str) -> Principal:
    principal = get_principal(request)
    if not principal.has(permission):
        audit = getattr(request.app.state, "audit", None)
        if audit is not None:
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
        raise ApiError("FORBIDDEN", "没有执行该操作的权限", details={"permission": permission})
    return principal


def _organization_id(principal: Principal) -> str:
    if not principal.organization_id:
        raise ApiError("INVALID_REQUEST", "账号未归属组织")
    return principal.organization_id


# --------------------------------------------------------------------------- 侦察记录


@router.get("/recon-records", summary="侦察记录列表")
def list_recon_records(
    request: Request,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    principal = _principal(request, "recon:read_assigned")
    code, payload = _fwd(
        request,
        "GET",
        "/internal/v1/recon-records",
        params={
            "viewer_user_id": principal.user_id,
            "status": status,
            "page": page,
            "page_size": page_size,
        },
    )
    items = payload.get("items", [])
    if priority:
        items = [item for item in items if item.get("priority") == priority]
    return JSONResponse(
        {
            "items": items,
            "page": payload.get("page", page),
            "page_size": payload.get("page_size", page_size),
            "total": payload.get("total", len(items)),
        },
        status_code=code,
    )


@router.post("/recon-records", status_code=201, summary="创建侦察草稿")
def create_recon_record(payload: ReconRecordWrite, request: Request) -> JSONResponse:
    principal = _principal(request, "recon:create")
    body = payload.model_dump()
    body["owner_id"] = principal.user_id
    body["organization_id"] = _organization_id(principal)
    code, record = _fwd(
        request, "POST", "/internal/v1/recon-records", json_body=body, status=201
    )
    return JSONResponse(record, status_code=code)


@router.get("/recon-records/{record_id}", summary="侦察记录详情")
def get_recon_record(record_id: str, request: Request) -> JSONResponse:
    _principal(request, "recon:read_assigned")
    code, record = _fwd(request, "GET", f"/internal/v1/recon-records/{record_id}")
    return JSONResponse(record, status_code=code)


@router.patch("/recon-records/{record_id}", summary="编辑侦察草稿")
def update_recon_record(
    record_id: str, payload: ReconRecordPatch, request: Request
) -> JSONResponse:
    _principal(request, "recon:edit_own_draft")
    code, record = _fwd(
        request,
        "PATCH",
        f"/internal/v1/recon-records/{record_id}",
        json_body=payload.model_dump(exclude_none=True),
    )
    return JSONResponse(record, status_code=code)


@router.post("/recon-records/{record_id}/submit", summary="提交侦察记录并指派分析员")
def submit_recon_record(
    record_id: str, payload: ReconSubmitRequest, request: Request
) -> JSONResponse:
    _principal(request, "recon:submit")
    code, record = _fwd(
        request,
        "POST",
        f"/internal/v1/recon-records/{record_id}/submit",
        json_body=payload.model_dump(exclude_none=True),
    )
    return JSONResponse(record, status_code=code)


# --------------------------------------------------------------------------- 分析报告


@router.get("/analysis-reports", summary="分析报告列表")
def list_analysis_reports(
    request: Request,
    status: str | None = Query(default=None),
    recon_record_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    principal = _principal(request, "analysis:read_assigned")
    code, payload = _fwd(
        request,
        "GET",
        "/internal/v1/analysis-reports",
        params={
            "viewer_user_id": principal.user_id,
            "status": status,
            "recon_record_id": recon_record_id,
            "page": page,
            "page_size": page_size,
        },
    )
    return JSONResponse(payload, status_code=code)


@router.post("/analysis-reports", status_code=201, summary="创建分析报告")
def create_analysis_report(payload: AnalysisReportWrite, request: Request) -> JSONResponse:
    principal = _principal(request, "analysis:create")
    body = payload.model_dump()
    body["author_id"] = principal.user_id
    body["organization_id"] = _organization_id(principal)
    code, report = _fwd(
        request, "POST", "/internal/v1/analysis-reports", json_body=body, status=201
    )
    return JSONResponse(report, status_code=code)


@router.get("/analysis-reports/{report_id}", summary="分析报告详情")
def get_analysis_report(report_id: str, request: Request) -> JSONResponse:
    _principal(request, "analysis:read_assigned")
    code, report = _fwd(request, "GET", f"/internal/v1/analysis-reports/{report_id}")
    return JSONResponse(report, status_code=code)


@router.patch("/analysis-reports/{report_id}", summary="编辑分析报告草稿")
def update_analysis_report(
    report_id: str, payload: AnalysisReportPatch, request: Request
) -> JSONResponse:
    _principal(request, "analysis:edit_own_draft")
    code, report = _fwd(
        request,
        "PATCH",
        f"/internal/v1/analysis-reports/{report_id}",
        json_body=payload.model_dump(exclude_none=True),
    )
    return JSONResponse(report, status_code=code)


@router.post("/analysis-reports/{report_id}/submit", summary="提交分析报告并指派决策员")
def submit_analysis_report(
    report_id: str, payload: AnalysisReportSubmitRequest, request: Request
) -> JSONResponse:
    _principal(request, "analysis:submit")
    body = {
        "expected_version": payload.expected_version,
        "decision_maker_ids": payload.decision_maker_ids,
        "ai_content_confirmed": payload.ai_content_confirmed,
    }
    code, report = _fwd(
        request,
        "POST",
        f"/internal/v1/analysis-reports/{report_id}/submit",
        json_body=body,
    )
    return JSONResponse(report, status_code=code)
