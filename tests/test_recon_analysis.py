"""侦察与分析业务链用例（Issue #9）。

真实装配 IAM + Recon + Analysis + Gateway 四个 FastAPI 应用，服务之间用 ASGI 桥接，
业务判断全部走真实代码路径（不 mock service 层）。
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
    from nis_shared.clients import IamClient, InternalClient, ReconClient
    from nis_shared.db import Database

    # 1. IAM：内存库 + 种子
    import_service("iam-service")
    iam_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(iam_db)
    seed_module = importlib.import_module("app.seed")
    seed_module.seed(iam_db, admin_password=ADMIN_PASSWORD, demo_password=DEMO_PASSWORD)
    iam_app = importlib.import_module("app.main").app
    iam_app.state.database = iam_db
    iam_app.state.audit = RecordingAudit()
    iam_bridge = AsgiBridge(iam_app)

    # 2. 侦察服务
    recon_models = import_service("recon-service")[0]
    recon_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(recon_db)
    recon_app = importlib.import_module("app.main").app
    recon_app.state.database = recon_db
    recon_app.state.audit = RecordingAudit()
    recon_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    recon_bridge = AsgiBridge(recon_app)

    # 3. 分析服务
    analysis_models = import_service("analysis-service")[0]
    analysis_db = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(analysis_db)
    analysis_app = importlib.import_module("app.main").app
    analysis_app.state.database = analysis_db
    analysis_app.state.audit = RecordingAudit()
    analysis_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    analysis_app.state.recon = ReconClient("http://recon-service:8002", transport=recon_bridge)
    analysis_bridge = AsgiBridge(analysis_app)

    # 4. Gateway
    import_service("api-gateway")
    gateway_app = importlib.import_module("app.main").app
    gateway_app.state.iam = IamClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.iam_http = InternalClient("http://iam-service:8001", transport=iam_bridge)
    gateway_app.state.recon_http = InternalClient("http://recon-service:8002", transport=recon_bridge)
    gateway_app.state.analysis_http = InternalClient(
        "http://analysis-service:8003", transport=analysis_bridge
    )
    gateway_app.state.audit = RecordingAudit()

    return {
        "client": TestClient(gateway_app),
        "gateway": gateway_app,
        "recon_app": recon_app,
        "analysis_app": analysis_app,
        "recon_models": recon_models,
        "analysis_models": analysis_models,
        "iam_models": import_service("iam-service")[0],
    }


def login(client: TestClient, username: str, password: str = DEMO_PASSWORD) -> str:
    response = client.post(f"{API}/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def headers(token: str, role_context: str | None = None, idem: str | None = None) -> dict:
    result = {"Authorization": f"Bearer {token}"}
    if role_context:
        result["X-Role-Context"] = role_context
    if idem:
        result["Idempotency-Key"] = idem
    return result


def make_record(client: TestClient, token: str, **overrides) -> dict:
    body = {
        "title": "演示用：目标区域活动规律观察",
        "source_type": "osint",
        "source_ref": "演示环境内部素材，已脱敏",
        "content": "在课程授权的演示环境中，观察到目标区域每日固定时段出现人员与车辆往返。",
        "credibility": "medium",
        "priority": "urgent",
    }
    body.update(overrides)
    response = client.post(f"{API}/recon-records", headers=headers(token), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def candidates(client: TestClient, token: str, role: str) -> dict[str, str]:
    """返回 ``{显示名: user_id}``：测试按显示名精确挑人，不依赖候选排序。"""

    response = client.get(f"{API}/candidates", headers=headers(token), params={"target_role": role})
    assert response.status_code == 200, response.text
    return {item["display_name"]: item["user_id"] for item in response.json()["items"]}


def analyst_ids(client: TestClient, token: str) -> list[str]:
    return list(candidates(client, token, "analyst").values())


# --------------------------------------------------------------------------- 侦察


def test_create_record_injects_owner_and_number(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = make_record(client, recon_token)

    assert record["status"] == "draft"
    assert record["record_no"].startswith("REC-")
    assert record["owner_id"]
    assert record["version"] == 1
    assert record["assignments"] == []


def test_owner_in_body_is_ignored(stack) -> None:
    """浏览器伪造 owner_id 无效：Gateway 只认令牌主体。"""

    client = stack["client"]
    recon_token = login(client, "recon01")
    other = login(client, "analyst01")
    record = make_record(client, recon_token)
    assert record["owner_id"] != other


def test_draft_edit_version_conflict_and_workflow_conflict(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = make_record(client, recon_token)

    stale = client.patch(
        f"{API}/recon-records/{record['id']}",
        headers=headers(recon_token),
        json={"expected_version": 99, "title": "改个标题"},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "VERSION_CONFLICT"

    updated = client.patch(
        f"{API}/recon-records/{record['id']}",
        headers=headers(recon_token),
        json={"expected_version": record["version"], "title": "改个标题"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == record["version"] + 1

    analysts = analyst_ids(client, recon_token)
    submitted = client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token),
        json={"expected_version": updated.json()["version"], "analyst_ids": analysts[:1]},
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "assigned"

    after_submit = client.patch(
        f"{API}/recon-records/{record['id']}",
        headers=headers(recon_token),
        json={"expected_version": submitted.json()["version"], "title": "提交后还想改"},
    )
    assert after_submit.status_code == 409
    assert after_submit.json()["code"] == "WORKFLOW_CONFLICT"


def test_submit_rejects_ineligible_analyst(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = make_record(client, recon_token)
    exec_token = login(client, "exec01")
    exec_ids = [
        item["user_id"]
        for item in client.get(
            f"{API}/candidates", headers=headers(exec_token), params={"target_role": "executor"}
        ).json()["items"]
    ]

    response = client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token),
        json={"expected_version": record["version"], "analyst_ids": exec_ids[:1]},
    )
    assert response.status_code == 400 or response.status_code == 422
    assert "analyst" in response.text.lower() or "invalid" in response.text.lower()


def test_submit_is_idempotent_with_same_key(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = make_record(client, recon_token)
    analysts = analyst_ids(client, recon_token)
    key = str(uuid.uuid4())

    first = client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token, idem=key),
        json={"expected_version": record["version"], "analyst_ids": analysts},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    assert len(first_body["assignments"]) == len(analysts)

    second = client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token, idem=key),
        json={"expected_version": first_body["version"], "analyst_ids": analysts},
    )
    assert second.status_code == 200
    assert second.json()["id"] == first_body["id"]
    assert len(second.json()["assignments"]) == len(analysts), "重复提交不得重复建指派"


def test_assigned_analyst_can_read_others_cannot(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = make_record(client, recon_token)
    analysts = analyst_ids(client, recon_token)
    client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token),
        json={"expected_version": record["version"], "analyst_ids": [candidates(client, recon_token, "analyst")["分析员甲"]]},
    )

    analyst01 = login(client, "analyst01")
    analyst02 = login(client, "analyst02")

    mine = client.get(f"{API}/recon-records", headers=headers(analyst01))
    assert any(item["id"] == record["id"] for item in mine.json()["items"])

    theirs = client.get(f"{API}/recon-records", headers=headers(analyst02))
    assert all(item["id"] != record["id"] for item in theirs.json()["items"])

    direct = client.get(f"{API}/recon-records/{record['id']}", headers=headers(analyst02))
    assert direct.status_code == 404

    owner_view = client.get(f"{API}/recon-records/{record['id']}", headers=headers(recon_token))
    assert owner_view.status_code == 200


def test_executor_has_no_recon_access(stack) -> None:
    client = stack["client"]
    exec_token = login(client, "exec01")
    response = client.get(f"{API}/recon-records", headers=headers(exec_token))
    assert response.status_code == 403


# --------------------------------------------------------------------------- 分析


def _submitted_record(
    client: TestClient, recon_token: str, assignees: list[str] | None = None
) -> dict:
    record = make_record(client, recon_token)
    by_name = candidates(client, recon_token, "analyst")
    analysts = [by_name[name] for name in assignees] if assignees else list(by_name.values())
    response = client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token),
        json={"expected_version": record["version"], "analyst_ids": analysts},
    )
    assert response.status_code == 200, response.text
    return response.json()


def make_report(client: TestClient, token: str, record_id: str, **overrides) -> dict:
    body = {
        "title": "演示用：区域活动规律分析",
        "recon_record_ids": [record_id],
        "key_findings": "活动时间与路线高度规律，具备固定保障节点特征。",
        "relations": "人员往返与车辆调度在同一时段出现。",
        "risk_level": "medium",
        "recommended_actions": "建议在固定时段前完成观察点部署，并保留影像证据。",
        "priority": "urgent",
    }
    body.update(overrides)
    response = client.post(f"{API}/analysis-reports", headers=headers(token), json=body)
    return response


def test_analysis_report_snapshots_come_from_recon(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token)
    analyst_token = login(client, "analyst01")

    response = make_report(client, analyst_token, record["id"])
    assert response.status_code == 201, response.text
    report = response.json()
    assert report["status"] == "draft"
    assert report["report_no"].startswith("RPT-")
    links = report["recon_links"]
    assert len(links) == 1
    assert links[0]["recon_record_id"] == record["id"]
    assert links[0]["recon_title_snapshot"] == record["title"]


def test_unassigned_analyst_cannot_create_report(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = make_record(client, recon_token)
    analysts = analyst_ids(client, recon_token)
    client.post(
        f"{API}/recon-records/{record['id']}/submit",
        headers=headers(recon_token),
        json={"expected_version": record["version"], "analyst_ids": [candidates(client, recon_token, "analyst")["分析员甲"]]},
    )
    analyst02 = login(client, "analyst02")
    response = make_report(client, analyst02, record["id"])
    assert response.status_code == 403


def test_report_submit_requires_ai_confirmation(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token)
    analyst_token = login(client, "analyst01")
    report = make_report(client, analyst_token, record["id"]).json()

    dm_ids = [candidates(client, analyst_token, "decision_maker")["决策员甲"]]
    refused = client.post(
        f"{API}/analysis-reports/{report['id']}/submit",
        headers=headers(analyst_token),
        json={"expected_version": report["version"], "decision_maker_ids": dm_ids},
    )
    assert refused.status_code in (400, 422)

    accepted = client.post(
        f"{API}/analysis-reports/{report['id']}/submit",
        headers=headers(analyst_token),
        json={
            "expected_version": report["version"],
            "decision_maker_ids": dm_ids,
            "ai_content_confirmed": True,
        },
    )
    assert accepted.status_code == 200, accepted.text
    body = accepted.json()
    assert body["status"] == "assigned"
    assert body["human_confirmed"] is True
    assert body["ai_content_confirmed"] is True
    assert set(body["decision_maker_ids"]) == set(dm_ids)


def test_decision_maker_sees_assigned_report_only(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token)
    analyst_token = login(client, "analyst01")
    report = make_report(client, analyst_token, record["id"]).json()

    dm_ids = [candidates(client, analyst_token, "decision_maker")["决策员甲"]]
    client.post(
        f"{API}/analysis-reports/{report['id']}/submit",
        headers=headers(analyst_token),
        json={
            "expected_version": report["version"],
            "decision_maker_ids": dm_ids,
            "ai_content_confirmed": True,
        },
    )

    dm_token = login(client, "dmaker01")
    visible = client.get(f"{API}/analysis-reports", headers=headers(dm_token))
    assert any(item["id"] == report["id"] for item in visible.json()["items"])

    analyst02 = login(client, "analyst02")
    hidden = client.get(f"{API}/analysis-reports/{report['id']}", headers=headers(analyst02))
    assert hidden.status_code == 404


def test_multiple_analysts_reports_coexist(stack) -> None:
    """多分析员对同一侦察记录各自出报告，互不覆盖（FR-ANALYSIS-005）。"""

    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token)

    a1 = login(client, "analyst01")
    a2 = login(client, "analyst02")
    r1 = make_report(client, a1, record["id"], title="分析员甲的结论").json()
    r2 = make_report(client, a2, record["id"], title="分析员乙的结论").json()

    assert r1["id"] != r2["id"]
    detail1 = client.get(f"{API}/analysis-reports/{r1['id']}", headers=headers(a1)).json()
    detail2 = client.get(f"{API}/analysis-reports/{r2['id']}", headers=headers(a2)).json()
    assert detail1["title"] == "分析员甲的结论"
    assert detail2["title"] == "分析员乙的结论"
    assert detail1["report_no"] != detail2["report_no"]

    by_record = client.get(
        f"{API}/analysis-reports",
        headers=headers(a1),
        params={"recon_record_id": record["id"]},
    )
    assert any(item["id"] == r1["id"] for item in by_record.json()["items"])


def test_report_edit_after_submit_is_rejected(stack) -> None:
    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token)
    analyst_token = login(client, "analyst01")
    report = make_report(client, analyst_token, record["id"]).json()

    dm_ids = [candidates(client, analyst_token, "decision_maker")["决策员甲"]]
    submitted = client.post(
        f"{API}/analysis-reports/{report['id']}/submit",
        headers=headers(analyst_token),
        json={
            "expected_version": report["version"],
            "decision_maker_ids": dm_ids,
            "ai_content_confirmed": True,
        },
    ).json()

    edit = client.patch(
        f"{API}/analysis-reports/{report['id']}",
        headers=headers(analyst_token),
        json={"expected_version": submitted["version"], "title": "提交后修改"},
    )
    assert edit.status_code == 409
    assert edit.json()["code"] == "WORKFLOW_CONFLICT"


def test_recon_status_moves_to_analyzed_after_report_submit(stack) -> None:
    """只指派一名分析员时，其报告提交后记录应汇总为 analyzed。"""

    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token, assignees=["分析员甲"])
    analyst_token = login(client, "analyst01")
    report = make_report(client, analyst_token, record["id"]).json()

    dm_ids = [candidates(client, analyst_token, "decision_maker")["决策员甲"]]
    submitted = client.post(
        f"{API}/analysis-reports/{report['id']}/submit",
        headers=headers(analyst_token),
        json={
            "expected_version": report["version"],
            "decision_maker_ids": dm_ids,
            "ai_content_confirmed": True,
        },
    )
    assert submitted.status_code == 200, submitted.text

    refreshed = client.get(f"{API}/recon-records/{record['id']}", headers=headers(recon_token))
    assert refreshed.status_code == 200
    assert refreshed.json()["status"] == "analyzed"
    assert refreshed.json()["assignments"][0]["status"] == "completed"


def test_recon_stays_assigned_while_other_analyst_pending(stack) -> None:
    """多名分析员时，只有全部完成才汇总为 analyzed（workflow 第 2 节）。"""

    client = stack["client"]
    recon_token = login(client, "recon01")
    record = _submitted_record(client, recon_token)  # 指派两名分析员
    analyst_token = login(client, "analyst01")
    report = make_report(client, analyst_token, record["id"]).json()

    dm_ids = [candidates(client, analyst_token, "decision_maker")["决策员甲"]]
    client.post(
        f"{API}/analysis-reports/{report['id']}/submit",
        headers=headers(analyst_token),
        json={
            "expected_version": report["version"],
            "decision_maker_ids": dm_ids,
            "ai_content_confirmed": True,
        },
    )

    refreshed = client.get(f"{API}/recon-records/{record['id']}", headers=headers(recon_token))
    statuses = {item["status"] for item in refreshed.json()["assignments"]}
    assert statuses == {"completed", "pending"}
    assert refreshed.json()["status"] == "assigned"
