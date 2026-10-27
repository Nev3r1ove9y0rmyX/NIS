"""Gateway 决策与执行路由（/api/v1）。

与侦察/分析一致的三条规则：身份从令牌注入、入口鉴权 + 下游二次鉴权、幂等键透传。
另外这里贯彻决策 D-01：指令总体状态只从 decision-service 读，Gateway 不做汇总计算。
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.proxy import forward, forward_bytes
from nis_shared.auth import Principal, get_principal
from nis_shared.errors import ApiError

router = APIRouter(prefix="/api/v1", tags=["指令与执行"])

PRIORITY = "^(normal|urgent)$"
OUTCOME = "^(success|failure|partial)$"


class CommandWrite(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    objective: str = Field(min_length=2, max_length=500)
    content: str = Field(min_length=10, max_length=8000)
    priority: str = Field(pattern=PRIORITY)
    deadline: datetime | None = None
    source_report_id: str = Field(min_length=36, max_length=36)


class CommandPatch(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=2, max_length=200)
    objective: str | None = Field(default=None, min_length=2, max_length=500)
    content: str | None = Field(default=None, min_length=10, max_length=8000)
    priority: str | None = Field(default=None, pattern=PRIORITY)
    deadline: datetime | None = None


class CommandIssueRequest(BaseModel):
    expected_version: int = Field(ge=1)
    executor_ids: list[str] = Field(min_length=1)
    conflict_acknowledged: bool = False


class CommandCancelRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=500)


class TransitionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class RejectRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=2, max_length=500)


class EvidenceItem(BaseModel):
    file_name: str = Field(max_length=255)
    media_type: str = Field(max_length=127)
    size_bytes: int = Field(default=0, ge=0)
    sha256: str = Field(pattern="^[a-f0-9]{64}$")


class CompleteRequest(BaseModel):
    expected_version: int = Field(ge=1)
    outcome: str = Field(pattern=OUTCOME)
    summary: str = Field(min_length=1, max_length=2000)
    detail: str | None = Field(default=None, max_length=8000)
    evidence: list[EvidenceItem] = Field(default_factory=list)


def _fwd(request: Request, method: str, path: str, **kwargs):  # noqa: ANN003, ANN201
    upstream = "execution" if path.startswith("/internal/v1/assignments") else "decision"
    if path.endswith("/summary"):
        upstream = "execution"
    return forward(request, method, path, upstream=upstream, **kwargs)


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


# --------------------------------------------------------------------------- 指令


@router.get("/commands", summary="指令列表")
def list_commands(
    request: Request,
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    principal = _principal(request, "command:read_assigned")
    code, payload = _fwd(
        request,
        "GET",
        "/internal/v1/commands",
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


@router.post("/commands", status_code=201, summary="创建指令草稿")
def create_command(payload: CommandWrite, request: Request) -> JSONResponse:
    principal = _principal(request, "command:create")
    if not principal.organization_id:
        raise ApiError("INVALID_REQUEST", "账号未归属组织")
    body = payload.model_dump(mode="json")
    body["decision_maker_id"] = principal.user_id
    body["organization_id"] = principal.organization_id
    code, command = _fwd(request, "POST", "/internal/v1/commands", json_body=body, status=201)
    return JSONResponse(command, status_code=code)


@router.get("/commands/conflicts", summary="下达前冲突检查")
def check_conflicts(
    request: Request,
    source_report_id: str = Query(min_length=36, max_length=36),
    objective: str | None = Query(default=None),
    exclude_command_id: str | None = Query(default=None),
) -> JSONResponse:
    _principal(request, "command:issue")
    code, payload = _fwd(
        request,
        "GET",
        "/internal/v1/commands/conflicts",
        params={
            "source_report_id": source_report_id,
            "objective": objective,
            "exclude_command_id": exclude_command_id,
        },
    )
    return JSONResponse(payload, status_code=code)


@router.get("/commands/{command_id}", summary="指令详情")
def get_command(command_id: str, request: Request) -> JSONResponse:
    _principal(request, "command:read_assigned")
    code, command = _fwd(request, "GET", f"/internal/v1/commands/{command_id}")
    return JSONResponse(command, status_code=code)


@router.patch("/commands/{command_id}", summary="编辑指令草稿")
def update_command(command_id: str, payload: CommandPatch, request: Request) -> JSONResponse:
    _principal(request, "command:create")
    code, command = _fwd(
        request,
        "PATCH",
        f"/internal/v1/commands/{command_id}",
        json_body=payload.model_dump(mode="json", exclude_none=True),
    )
    return JSONResponse(command, status_code=code)


@router.post("/commands/{command_id}/issue", summary="下达指令")
def issue_command(command_id: str, payload: CommandIssueRequest, request: Request) -> JSONResponse:
    _principal(request, "command:issue")
    code, command = _fwd(
        request,
        "POST",
        f"/internal/v1/commands/{command_id}/issue",
        json_body=payload.model_dump(),
    )
    return JSONResponse(command, status_code=code)


@router.post("/commands/{command_id}/cancel", summary="取消指令")
def cancel_command(command_id: str, payload: CommandCancelRequest, request: Request) -> JSONResponse:
    _principal(request, "command:issue")
    code, command = _fwd(
        request,
        "POST",
        f"/internal/v1/commands/{command_id}/cancel",
        json_body=payload.model_dump(),
    )
    return JSONResponse(command, status_code=code)


@router.get("/commands/{command_id}/status", summary="指令总体状态")
def get_command_status(command_id: str, request: Request) -> JSONResponse:
    _principal(request, "command:read_assigned")
    code, payload = _fwd(request, "GET", f"/internal/v1/commands/{command_id}/status")
    return JSONResponse(payload, status_code=code)


@router.get("/commands/{command_id}/results", summary="各执行员结果")
def list_command_results(command_id: str, request: Request) -> JSONResponse:
    _principal(request, "command:read_assigned")
    code, payload = _fwd(request, "GET", f"/internal/v1/commands/{command_id}/summary")
    return JSONResponse({"items": payload.get("items", [])}, status_code=code)


# --------------------------------------------------------------------------- 执行分配


@router.get("/assignments", summary="本人执行任务")
def list_assignments(
    request: Request,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> JSONResponse:
    principal = _principal(request, "command:read_assigned")
    code, payload = _fwd(
        request,
        "GET",
        "/internal/v1/assignments",
        params={
            "executor_id": principal.user_id,
            "status": status,
            "page": page,
            "page_size": page_size,
        },
    )
    return JSONResponse(payload, status_code=code)


@router.get("/assignments/{assignment_id}", summary="执行任务详情")
def get_assignment(assignment_id: str, request: Request) -> JSONResponse:
    _principal(request, "command:read_assigned")
    code, item = _fwd(request, "GET", f"/internal/v1/assignments/{assignment_id}")
    return JSONResponse(item, status_code=code)


@router.get(
    "/assignments/{assignment_id}/evidence/{evidence_id}", summary="下载执行证据（受控代理）"
)
def download_execution_evidence(assignment_id: str, evidence_id: str, request: Request):
    _principal(request, "command:read_assigned")
    return forward_bytes(
        request,
        f"/internal/v1/assignments/{assignment_id}/evidence/{evidence_id}",
        permission="command:read_assigned",
        upstream="execution",
    )


@router.post("/assignments/{assignment_id}/accept", summary="接收指令")
def accept_assignment(
    assignment_id: str, payload: TransitionRequest, request: Request
) -> JSONResponse:
    _principal(request, "execution:respond")
    code, item = _fwd(
        request,
        "POST",
        f"/internal/v1/assignments/{assignment_id}/accept",
        json_body=payload.model_dump(),
    )
    return JSONResponse(item, status_code=code)


@router.post("/assignments/{assignment_id}/reject", summary="拒绝指令")
def reject_assignment(assignment_id: str, payload: RejectRequest, request: Request) -> JSONResponse:
    _principal(request, "execution:respond")
    code, item = _fwd(
        request,
        "POST",
        f"/internal/v1/assignments/{assignment_id}/reject",
        json_body=payload.model_dump(),
    )
    return JSONResponse(item, status_code=code)


@router.post("/assignments/{assignment_id}/start", summary="开始执行")
def start_assignment(
    assignment_id: str, payload: TransitionRequest, request: Request
) -> JSONResponse:
    _principal(request, "execution:update")
    code, item = _fwd(
        request,
        "POST",
        f"/internal/v1/assignments/{assignment_id}/start",
        json_body=payload.model_dump(),
    )
    return JSONResponse(item, status_code=code)


@router.post("/assignments/{assignment_id}/complete", summary="提交执行结果")
def complete_assignment(
    assignment_id: str, payload: CompleteRequest, request: Request
) -> JSONResponse:
    _principal(request, "execution:submit")
    code, item = _fwd(
        request,
        "POST",
        f"/internal/v1/assignments/{assignment_id}/complete",
        json_body=payload.model_dump(mode="json"),
    )
    return JSONResponse(item, status_code=code)
