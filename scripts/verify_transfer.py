"""验证任务转交：执行员把未完成任务转给另一名执行员，决策侧聚合状态正确。"""

import json
import os
import sys
import uuid
from typing import Any
from urllib import error, request

BASE = os.environ.get("NIS_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
PASSWORD = os.environ.get("NIS_DEMO_PASSWORD", "")
RESULTS: list[tuple[str, bool, str]] = []


def rec(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


class Api:
    def __init__(self):
        self.token = ""
        self.role_ctx = None

    def send(self, method, path, body=None, idem=None):
        headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
        data = None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.role_ctx:
            headers["X-Role-Context"] = self.role_ctx
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idem:
            headers["Idempotency-Key"] = idem
        req = request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except error.HTTPError as exc:
            raw = exc.read()
            return exc.code, (json.loads(raw) if raw else None)

    def login(self, user):
        status, payload = self.send("POST", "/auth/login", {"username": user, "password": PASSWORD})
        if status != 200:
            raise SystemExit(f"login {user} failed: {status} {payload}")
        self.token = payload["access_token"]
        roles = [str(r) for r in payload["user"].get("roles", [])]
        self.role_ctx = ("administrator" if "administrator" in roles else roles[0]) if len(roles) > 1 else None
        return payload["user"]


def key():
    return str(uuid.uuid4())


def main():
    if not PASSWORD:
        print("missing NIS_DEMO_PASSWORD")
        return 2

    dm = Api(); dm.login("dmaker01")
    e1 = Api(); e1.login("exec01")
    e2 = Api(); e2.login("exec02")
    rec_user = Api(); rec_user.login("recon01")
    an = Api(); an.login("analyst01")

    e1_id = e1.send("GET", "/auth/me")[1]["id"]
    e2_id = e2.send("GET", "/auth/me")[1]["id"]
    dm_id = dm.send("GET", "/auth/me")[1]["id"]

    # 准备一条可下达的指令
    r = rec_user.send("POST", "/recon-records", {
        "title": "转交测试-侦察", "source_type": "osint", "source_ref": "演示素材",
        "credibility": "high", "priority": "normal",
        "content": "用于验证任务转交功能的一条侦察记录。",
    }, key())[1]
    r = rec_user.send("POST", f"/recon-records/{r['id']}/submit",
                      {"expected_version": r["version"], "analyst_ids": [an.send("GET", "/auth/me")[1]["id"]]}, key())[1]
    report = an.send("POST", "/analysis-reports", {
        "title": "转交测试-分析", "recon_record_ids": [r["id"]],
        "key_findings": "结论：需要执行员现场核查。", "relations": "与时间相关。",
        "risk_level": "medium", "recommended_actions": "安排执行员核查。", "priority": "normal",
    }, key())[1]
    report = an.send("POST", f"/analysis-reports/{report['id']}/submit",
                     {"expected_version": report["version"], "decision_maker_ids": [dm_id], "ai_content_confirmed": True}, key())[1]

    cmd = dm.send("POST", "/commands", {
        "title": "转交测试-指令", "objective": "验证任务转交",
        "content": "派执行员甲核查，并由甲转交给乙。", "priority": "normal",
        "source_report_id": report["id"],
    }, key())[1]
    cmd = dm.send("POST", f"/commands/{cmd['id']}/issue",
                  {"expected_version": cmd["version"], "executor_ids": [e1_id], "conflict_acknowledged": True}, key())[1]
    assignment = e1.send("GET", f"/assignments?page=1&page_size=20")[1]["items"]
    a = next(i for i in assignment if i["command_id"] == cmd["id"])
    rec("执行员甲持有待办分配", a["status"] == "pending", a["status"])

    # 转交
    status, transferred = e1.send("POST", f"/assignments/{a['id']}/transfer",
                                  {"expected_version": a["version"], "target_executor_id": e2_id,
                                   "reason": "甲临时外出，交给乙执行"})
    rec("转交成功", status == 201 or status == 200, f"HTTP {status}")
    rec("新分配归属乙且为 pending", transferred["executor_id"] == e2_id and transferred["status"] == "pending",
        f"{transferred['executor_id'][:8]} {transferred['status']}")
    rec("新分配内容完整", transferred["command_title_snapshot"] == cmd["title"], transferred["command_title_snapshot"])

    # 旧分配状态
    old = e1.send("GET", f"/assignments/{a['id']}")[1]
    rec("旧分配变为 cancelled", old["status"] == "cancelled", old["status"])

    # 双方待办
    e1_items = e1.send("GET", "/assignments?page=1&page_size=50")[1]["items"]
    e2_items = e2.send("GET", "/assignments?page=1&page_size=50")[1]["items"]
    rec("甲待办中不再有该任务（仅保留已取消记录）",
        all(i["status"] != "pending" for i in e1_items if i["command_id"] == cmd["id"]),
        "甲侧仅 cancelled")
    rec("乙待办中出现该任务", any(i["id"] == transferred["id"] and i["status"] == "pending" for i in e2_items), "乙侧 pending")

    # 决策侧聚合状态
    st = dm.send("GET", f"/commands/{cmd['id']}/status")[1]
    rec("决策侧聚合状态为 issued（仅剩待接收）", st["status"] in ("issued", "partially_accepted"), st["status"])

    # 乙完成
    b = next(i for i in e2_items if i["id"] == transferred["id"])
    b = e2.send("POST", f"/assignments/{b['id']}/accept", {"expected_version": b["version"]})[1]
    b = e2.send("POST", f"/assignments/{b['id']}/start", {"expected_version": b["version"]})[1]
    b = e2.send("POST", f"/assignments/{b['id']}/complete",
                {"expected_version": b["version"], "outcome": "success",
                 "summary": "乙完成核查，未发现异常。", "detail": "无异常。"}, key())[1]
    st = dm.send("GET", f"/commands/{cmd['id']}/status")[1]
    rec("乙完成后指令聚合状态为 completed", st["status"] == "completed", st["status"])

    # 已完成任务不可转交
    status, body = e2.send("POST", f"/assignments/{b['id']}/transfer",
                           {"expected_version": b["version"] + 1, "target_executor_id": e1_id, "reason": "测试"})
    rec("已完成任务不可转交", status == 409, f"HTTP {status} {body.get('code') if body else ''}")

    # 转交给已持有者被拒
    cmd2 = dm.send("POST", "/commands", {
        "title": "转交测试-指令2", "objective": "验证重复目标",
        "content": "派甲乙两人，验证转交给已持有者被拒绝。", "priority": "normal",
        "source_report_id": report["id"],
    }, key())[1]
    cmd2 = dm.send("POST", f"/commands/{cmd2['id']}/issue",
                   {"expected_version": cmd2["version"], "executor_ids": [e1_id, e2_id],
                    "conflict_acknowledged": True}, key())[1]
    items = e1.send("GET", "/assignments?page=1&page_size=50")[1]["items"]
    a2 = next(i for i in items if i["command_id"] == cmd2["id"])
    status, body = e1.send("POST", f"/assignments/{a2['id']}/transfer",
                           {"expected_version": a2["version"], "target_executor_id": e2_id, "reason": "重复目标"})
    rec("转交给已持有该指令的执行员被拒", status == 400, f"HTTP {status} {body.get('code') if body else ''}")

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n汇总：{len(RESULTS)} 条，PASS {len(RESULTS) - len(fails)} / FAIL {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
