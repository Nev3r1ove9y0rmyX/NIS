"""指令与执行业务链用例（Issue #10）。

真实装配 IAM + Recon + Analysis + Decision + Execution + Gateway 六个应用，
跨服务调用用 ASGI 桥接，状态汇总完全走 decision-service 的单一入口（决策 D-01）。
"""

from __future__ import annotations

import importlib
import uuid

import pytest
from fastapi.testclient import TestClient

from conftest import ensure_schema, import_service
from test_auth import ADMIN_PASSWORD, DEMO_PASSWORD, AsgiBridge

API = "/api/v1"


class RecordingAudit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def write(self, **kwargs) -> bool:  # noqa: ANN003
        self.events.append(kwargs)
        return True


@pytest.fixture
def stack():
    from nis_shared.clients import (
        AnalysisClient,
        DecisionClient,
        ExecutionClient,
        IamClient,
        InternalClient,
        ReconClient,
    )
    from nis_shared.db import Database

    def fresh_db() -> Database:  # noqa: ANN202
        db = Database("sqlite+pysqlite:///:memory:")
        ensure_schema(db)
        return db

    # IAM
    import_service("iam-service")
    iam_db = fresh_db()
    seed_module = importlib.import_module("app.seed")
    seed_module.seed(iam_db, admin_password=ADMIN_PASSWORD, demo_password=DEMO_PASSWORD)
    iam_app = importlib.import_module("app.main").app
    iam_app.state.database = iam_db
    iam_app.state.audit = RecordingAudit()
    iam_bridge = AsgiBridge(iam_app)

    # Recon
    import_service("recon-service")
    recon_app = importlib.import_module("app.main").app
    recon_app.state.database = fresh_db()
    recon_app.state.audit = RecordingAudit()
    recon_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    recon_bridge = AsgiBridge(recon_app)

    # Analysis
    import_service("analysis-service")
    analysis_app = importlib.import_module("app.main").app
    analysis_app.state.database = fresh_db()
    analysis_app.state.audit = RecordingAudit()
    analysis_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    analysis_app.state.recon = ReconClient("http://recon-service:8002", transport=recon_bridge)
    analysis_bridge = AsgiBridge(analysis_app)

    # Decision 与 Execution 互相依赖：先建应用，再互相注入客户端
    import_service("decision-service")
    decision_app = importlib.import_module("app.main").app
    decision_db = fresh_db()
    decision_app.state.database = decision_db
    decision_app.state.audit = RecordingAudit()

    import_service("execution-service")
    execution_app = importlib.import_module("app.main").app
    execution_db = fresh_db()
    execution_app.state.database = execution_db
    execution_app.state.audit = RecordingAudit()

    decision_bridge = AsgiBridge(decision_app)
    execution_bridge = AsgiBridge(execution_app)

    decision_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    decision_app.state.analysis = AnalysisClient(
        "http://analysis-service:8003", transport=analysis_bridge
    )
    decision_app.state.execution = ExecutionClient(
        "http://execution-service:8005", transport=execution_bridge
    )
    execution_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    execution_app.state.decision = DecisionClient(
        "http://decision-service:8004", transport=decision_bridge
    )

    # Gateway
    import_service("api-gateway")
    gateway_app = importlib.import_module("app.main").app
    gateway_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.iam_http = InternalClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.recon_http = InternalClient("http://recon-service:8002", transport=recon_bridge)
    gateway_app.state.analysis_http = InternalClient(
        "http://analysis-service:8003", transport=analysis_bridge
    )
    gateway_app.state.decision_http = InternalClient(
        "http://decision-service:8004", transport=decision_bridge
    )
    gateway_app.state.execution_http = InternalClient(
        "http://execution-service:8005", transport=execution_bridge
    )
    gateway_app.state.audit = RecordingAudit()

    return {
        "client": TestClient(gateway_app),
        "decision": decision_app,
        "execution": execution_app,
        "decision_db": decision_db,
        "execution_db": execution_db,
    }


def login(client: TestClient, username: str, password: str = DEMO_PASSWORD) -> str:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token: str, idem: str | None = None) -> dict:
    result = {"Authorization": f"Bearer {token}"}
    if idem:
        result["Idempotency-Key"] = idem
    return result


def candidates(client: TestClient, token: str, role: str) -> dict[str, str]:
    response = client.get(f"{API}/candidates", headers=headers(token), params={"target_role": role})
    assert response.status_code == 200, response.text
    return {item["display_name"]: item["user_id"] for item in response.json()["items"]}


def _prepare_report(client: TestClient) -> dict:
    """跑完侦察 -> 分析两段，返回已指派给决策员甲的报告。"""

    recon = login(client, "recon01")
    analyst = login(client, "analyst01")

    record = client.post(
        f"{API}/recon-records",
        headers=headers(recon),
        json={
            "title": "演示用：目标区域活动规律观察",
            "source_type": "osint",
            "source_ref": "演示环境内部素材，已脱敏",
            "content": "在课程授权的演示环境中，观察到目标区域每日固定时段出现人员与车辆往返。",
            "credibility": "medium",
            "priority": "urgent",
        },
    ).json()
    analyst_id = candidates(client, recon, "analyst")["分析员甲"]
    submitted = client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon),
        json={"expected_version": record["version"], "analyst_ids": [analyst_id]},
    )
    assert submitted.status_code == 200, submitted.text

    report = client.post(
        f"{API}/analysis-reports",
        headers=headers(analyst),
        json={
            "title": "演示用：区域活动规律分析",
            "recon_record_ids": [record["id"]],
            "key_findings": "活动时间与路线高度规律，具备固定保障节点特征。",
            "relations": "人员往返与车辆调度在同一时段出现。",
            "risk_level": "medium",
            "recommended_actions": "建议在固定时段前完成观察点部署，并保留影像证据。",
            "priority": "urgent",
        },
    )
    assert report.status_code == 201, report.text
    dm_id = candidates(client, analyst, "decision_maker")["决策员甲"]
    done = client.post(
        f"{API}/analysis-reports/{report.json()['id']}/submit",
        headers=headers(analyst),
        json={
            "expected_version": report.json()["version"],
            "decision_maker_ids": [dm_id],
            "ai_content_confirmed": True,
        },
    )
    assert done.status_code == 200, done.text
    return done.json()


def _make_command(client: TestClient, token: str, report_id: str, title: str = "演示用：固定时段观察任务") -> dict:
    response = client.post(
        f"{API}/commands",
        headers=headers(token),
        json={
            "title": title,
            "objective": "在固定时段获取目标区域活动证据",
            "content": "提前 30 分钟到达观察点，按约定频段通联，只做观察与记录，不主动接触。",
            "priority": "urgent",
            "source_report_id": report_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _issue(client: TestClient, token: str, command: dict, executor_ids: list[str], *, ack: bool = False, idem: str | None = None):
    return client.post(
        f"{API}/commands/{command['id']}/issue",
        headers=headers(token, idem),
        json={
            "expected_version": command["version"],
            "executor_ids": executor_ids,
            "conflict_acknowledged": ack,
        },
    )


# --------------------------------------------------------------------------- 指令与下达


def test_create_and_issue_command_creates_assignments(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")

    command = _make_command(client, dm, report["id"])
    assert command["status"] == "draft"
    assert command["command_no"].startswith("CMD-")
    assert command["assignments"] == []

    issued = _issue(client, dm, command, [execs["执行员甲"], execs["执行员乙"]])
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert body["status"] == "issued"
    assert len(body["assignments"]) == 2
    assert {item["status"] for item in body["assignments"]} == {"pending"}


def test_issue_requires_conflict_acknowledgement(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")

    first = _make_command(client, dm, report["id"], title="第一条指令")
    assert _issue(client, dm, first, [execs["执行员甲"]]).status_code == 200

    second = _make_command(client, dm, report["id"], title="第二条指令")
    blocked = _issue(client, dm, second, [execs["执行员甲"]])
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "WORKFLOW_CONFLICT"
    assert blocked.json()["details"]["conflicts"]

    conflicts = client.get(
        f"{API}/commands/conflicts",
        headers=headers(dm),
        params={"source_report_id": report["id"]},
    )
    assert conflicts.status_code == 200
    assert conflicts.json()["has_conflict"] is True

    acknowledged = _issue(client, dm, second, [execs["执行员甲"]], ack=True)
    assert acknowledged.status_code == 200, acknowledged.text


def test_duplicate_issue_does_not_create_second_command(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    key = str(uuid.uuid4())

    first = _issue(client, dm, command, [execs["执行员甲"]], idem=key)
    assert first.status_code == 200, first.text

    replay = _issue(client, dm, command, [execs["执行员甲"]], idem=key)
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    exec_token = login(client, "exec01")
    mine = client.get(f"{API}/assignments", headers=headers(exec_token))
    assert mine.status_code == 200
    assert mine.json()["total"] == 1, "重复的下达请求不得产生第二条分配"

    commands = client.get(f"{API}/commands", headers=headers(dm))
    assert commands.json()["total"] == 1


def test_issue_rejects_ineligible_executor(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    analysts = candidates(client, dm, "analyst")
    command = _make_command(client, dm, report["id"])

    response = _issue(client, dm, command, [analysts["分析员甲"]])
    assert response.status_code in (400, 422)


# --------------------------------------------------------------------------- 状态汇总（D-01）


def test_command_status_follows_assignments(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    issued = _issue(client, dm, command, [execs["执行员甲"], execs["执行员乙"]]).json()

    by_executor = {item["executor_id"]: item["assignment_id"] for item in issued["assignments"]}
    a1 = by_executor[execs["执行员甲"]]
    a2 = by_executor[execs["执行员乙"]]

    e1 = login(client, "exec01")
    e2 = login(client, "exec02")

    def status() -> str:
        return client.get(f"{API}/commands/{command['id']}/status", headers=headers(dm)).json()["status"]

    first = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()
    assert client.post(
        f"{API}/assignments/{a1}/accept", headers=headers(e1), json={"expected_version": first["version"]}
    ).status_code == 200
    assert status() == "partially_accepted"

    second = client.get(f"{API}/assignments/{a2}", headers=headers(e2)).json()
    assert client.post(
        f"{API}/assignments/{a2}/accept", headers=headers(e2), json={"expected_version": second["version"]}
    ).status_code == 200
    assert status() == "accepted"

    started = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()
    assert client.post(
        f"{API}/assignments/{a1}/start", headers=headers(e1), json={"expected_version": started["version"]}
    ).status_code == 200
    assert status() == "executing"

    running = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()
    done = client.post(
        f"{API}/assignments/{a1}/complete",
        headers=headers(e1),
        json={
            "expected_version": running["version"],
            "outcome": "success",
            "summary": "按计划完成观察，取得 3 段连续记录。",
            "detail": "观察期间未发生异常接触。",
        },
    )
    assert done.status_code == 200, done.text
    assert status() == "partially_completed"

    second_started = client.get(f"{API}/assignments/{a2}", headers=headers(e2)).json()
    client.post(
        f"{API}/assignments/{a2}/start",
        headers=headers(e2),
        json={"expected_version": second_started["version"]},
    )
    running2 = client.get(f"{API}/assignments/{a2}", headers=headers(e2)).json()
    client.post(
        f"{API}/assignments/{a2}/complete",
        headers=headers(e2),
        json={
            "expected_version": running2["version"],
            "outcome": "success",
            "summary": "补充观察完成。",
        },
    )
    assert status() == "completed"


def test_assignments_are_isolated_between_executors(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    issued = _issue(client, dm, command, [execs["执行员甲"], execs["执行员乙"]]).json()
    a1 = {item["executor_id"]: item["assignment_id"] for item in issued["assignments"]}[
        execs["执行员甲"]
    ]

    e2 = login(client, "exec02")
    other = client.get(f"{API}/assignments/{a1}", headers=headers(e2))
    assert other.status_code in (403, 404)

    listing = client.get(f"{API}/assignments", headers=headers(e2))
    assert listing.status_code == 200
    assert all(item["id"] != a1 for item in listing.json()["items"])


def test_repeated_completion_is_rejected(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    issued = _issue(client, dm, command, [execs["执行员甲"]]).json()
    a1 = issued["assignments"][0]["assignment_id"]
    e1 = login(client, "exec01")

    accepted = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()
    client.post(f"{API}/assignments/{a1}/accept", headers=headers(e1), json={"expected_version": accepted["version"]})
    started = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()
    client.post(f"{API}/assignments/{a1}/start", headers=headers(e1), json={"expected_version": started["version"]})
    running = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()

    first = client.post(
        f"{API}/assignments/{a1}/complete",
        headers=headers(e1),
        json={"expected_version": running["version"], "outcome": "success", "summary": "完成观察。"},
    )
    assert first.status_code == 200, first.text

    again = client.post(
        f"{API}/assignments/{a1}/complete",
        headers=headers(e1),
        json={"expected_version": first.json()["version"], "outcome": "success", "summary": "再来一次。"},
    )
    assert again.status_code == 409
    assert again.json()["code"] == "WORKFLOW_CONFLICT"

    results = client.get(f"{API}/commands/{command['id']}/results", headers=headers(dm))
    assert results.status_code == 200
    assert len(results.json()["items"]) == 1


def test_reject_flows_to_command_status(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    issued = _issue(client, dm, command, [execs["执行员甲"]]).json()
    a1 = issued["assignments"][0]["assignment_id"]
    e1 = login(client, "exec01")

    pending = client.get(f"{API}/assignments/{a1}", headers=headers(e1)).json()
    rejected = client.post(
        f"{API}/assignments/{a1}/reject",
        headers=headers(e1),
        json={"expected_version": pending["version"], "reason": "不在本单位任务范围"},
    )
    assert rejected.status_code == 200, rejected.text
    assert rejected.json()["status"] == "rejected"

    status = client.get(f"{API}/commands/{command['id']}/status", headers=headers(dm)).json()
    assert status["status"] == "rejected"


def test_cancel_command(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    issued = _issue(client, dm, command, [execs["执行员甲"]]).json()

    cancelled = client.post(
        f"{API}/commands/{command['id']}/cancel",
        headers=headers(dm),
        json={"expected_version": issued["version"], "reason": "目标已失效"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["cancel_reason"] == "目标已失效"


def test_decision_maker_cannot_create_command_from_unassigned_report(stack) -> None:
    """报告必须指派给本人：另一名决策员不能拿别人的报告下指令。"""

    client = stack["client"]
    report = _prepare_report(client)
    admin = login(client, "admin", ADMIN_PASSWORD)
    response = client.post(
        f"{API}/commands",
        headers={**headers(admin), "X-Role-Context": "decision_maker"},
        json={
            "title": "越权指令",
            "objective": "尝试用未指派报告",
            "content": "这条指令不应该被创建成功。",
            "priority": "normal",
            "source_report_id": report["id"],
        },
    )
    assert response.status_code in (403, 404)


def test_executor_cannot_read_command_of_others(stack) -> None:
    client = stack["client"]
    report = _prepare_report(client)
    dm = login(client, "dmaker01")
    execs = candidates(client, dm, "executor")
    command = _make_command(client, dm, report["id"])
    _issue(client, dm, command, [execs["执行员乙"]])

    e1 = login(client, "exec01")
    response = client.get(f"{API}/commands/{command['id']}", headers=headers(e1))
    assert response.status_code == 404
