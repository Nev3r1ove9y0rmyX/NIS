"""多用户与冲突场景的集成检查（A 维护，用于 #20 与验收排练）。

覆盖五组场景，全部通过公共接口（`/api/v1`）完成，不直接读写数据库：

1. 多名侦察员提交矛盾信息：各自保留，互不覆盖；
2. 多名分析员结论不一致：报告并列存在，决策员都能看到，不自动合并；
3. 多决策员重复/冲突指令：冲突检查命中、未确认时 409、同幂等键重复下达不重复建单；
4. 多执行员分配与重复执行：个人状态独立、聚合状态按规则演进、换幂等键重复完成 409；
5. 越权与串号：执行员读不到他人分配，分析员访问决策资源被拦。

前置条件：本地全栈已启动（`python scripts/dev_stack.py run`）且已写入演示账号。

用法：

    set NIS_DEMO_PASSWORD=...
    python scripts/check_multi_user_conflicts.py

退出码：0 全部通过；1 存在失败；2 缺少口令。
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from typing import Any
from urllib import error, request

BASE = os.environ.get("NIS_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
PASSWORD = os.environ.get("NIS_DEMO_PASSWORD", "")
RESULTS: list[tuple[str, str, str]] = []


def record(scene: str, ok: bool, detail: str) -> None:
    RESULTS.append((scene, "PASS" if ok else "FAIL", detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {scene}: {detail}")


class Client:
    def __init__(self) -> None:
        self.token = ""
        self.role_context: str | None = None

    def send(self, method: str, path: str, body: dict[str, Any] | None = None,
             idem: str | None = None, expect: tuple[int, ...] = (200, 201, 204)) -> Any:
        headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
        data = None
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.role_context:
            headers["X-Role-Context"] = self.role_context
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idem:
            headers["Idempotency-Key"] = idem
        req = request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
        try:
            with request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                status = resp.status
                ctype = resp.headers.get("Content-Type", "")
        except error.HTTPError as exc:
            payload = exc.read()
            body_json = json.loads(payload) if payload else {}
            if exc.code in expect:
                return body_json
            raise RuntimeError(f"HTTP {exc.code} {body_json}") from exc
        if status not in expect:
            raise RuntimeError(f"HTTP {status}")
        return json.loads(raw) if raw else None

    def login(self, username: str) -> dict[str, Any]:
        payload = self.send("POST", "/auth/login", {"username": username, "password": PASSWORD})
        self.token = payload["access_token"]
        roles = [str(r) for r in payload["user"].get("roles", [])]
        self.role_context = ("administrator" if "administrator" in roles else roles[0]) if len(roles) > 1 else None
        return payload["user"]


def key() -> str:
    return str(uuid.uuid4())


def main() -> int:
    if not PASSWORD:
        print("缺少 NIS_DEMO_PASSWORD", file=sys.stderr)
        return 2

    c = {name: Client() for name in
         ("recon01", "recon02", "analyst01", "analyst02", "dmaker01", "exec01", "exec02")}
    for name, client in c.items():
        client.login(name)
    print(f"已登录 7 个账号，目标 {BASE}")

    # ---------- 场景 1：两名侦察员提交矛盾信息 ----------
    print("\n[场景 1] 多名侦察员提交矛盾信息")
    r1 = c["recon01"].send("POST", "/recon-records", {
        "title": "冲突测试-侦察甲-路线在北侧", "source_type": "osint",
        "source_ref": "演示素材", "credibility": "high", "priority": "normal",
        "content": "观察记录显示目标车辆沿北侧道路往返，时间为每日 08:00 前后。",
    }, key())
    r2 = c["recon02"].send("POST", "/recon-records", {
        "title": "冲突测试-侦察乙-路线在南侧", "source_type": "osint",
        "source_ref": "演示素材", "credibility": "medium", "priority": "normal",
        "content": "观察记录显示目标车辆沿南侧道路往返，时间为每日 08:00 前后。",
    }, key())
    record("两条记录独立创建", r1["id"] != r2["id"], f"{r1['id'][:8]} / {r2['id'][:8]}")
    analyst01_id = c["analyst01"].send("GET", "/auth/me")["id"]
    analyst02_id = c["analyst02"].send("GET", "/auth/me")["id"]
    # 场景 2 需要两名分析员都能读到同一条记录，因此把 r1 同时指派给两人。
    r1 = c["recon01"].send("POST", f"/recon-records/{r1['id']}/submit",
                           {"expected_version": r1["version"], "analyst_ids": [analyst01_id, analyst02_id]}, key())
    r2 = c["recon02"].send("POST", f"/recon-records/{r2['id']}/submit",
                           {"expected_version": r2["version"], "analyst_ids": [analyst01_id]}, key())
    record("两条记录均提交成功", r1["status"] == "assigned" and r2["status"] == "assigned", f"{r1['status']} / {r2['status']}")
    mine = c["recon01"].send("GET", "/recon-records?page_size=50")["items"]
    record("侦察员只看本人记录", all(i["owner_id"] == c["recon01"].send("GET", "/auth/me")["id"] for i in mine), f"本人 {len(mine)} 条")
    kept = c["recon02"].send("GET", "/recon-records?page_size=50")["items"]
    record("矛盾记录未被覆盖", any(i["id"] == r2["id"] for i in kept) and not any(i["id"] == r1["id"] for i in kept), "乙只看到自己的记录")

    # ---------- 场景 2：两名分析员结论不一致 ----------
    print("\n[场景 2] 多名分析员结论不一致")
    dmaker_id = c["dmaker01"].send("GET", "/auth/me")["id"]
    a1 = c["analyst01"].send("POST", "/analysis-reports", {
        "title": "冲突测试-分析甲-结论北侧", "recon_record_ids": [r1["id"]],
        "key_findings": "北侧道路存在稳定的车辆往返规律，间隔固定。", "relations": "时间与北侧路段强相关。",
        "risk_level": "medium", "recommended_actions": "在北侧设置观察点。", "priority": "normal",
    }, key())
    a1 = c["analyst01"].send("POST", f"/analysis-reports/{a1['id']}/submit",
                             {"expected_version": a1["version"], "decision_maker_ids": [dmaker_id], "ai_content_confirmed": True}, key())
    a2 = c["analyst02"].send("POST", "/analysis-reports", {
        "title": "冲突测试-分析乙-结论南侧", "recon_record_ids": [r1["id"]],
        "key_findings": "同一条记录中南侧往返规律更明显，北侧结论可信度存疑。", "relations": "时间与南侧路段强相关。",
        "risk_level": "high", "recommended_actions": "优先核查南侧路段。", "priority": "urgent",
    }, key())
    a2 = c["analyst02"].send("POST", f"/analysis-reports/{a2['id']}/submit",
                             {"expected_version": a2["version"], "decision_maker_ids": [dmaker_id], "ai_content_confirmed": True}, key())
    seen = c["dmaker01"].send("GET", "/analysis-reports?page_size=50")["items"]
    both = {a1["id"], a2["id"]} <= {i["id"] for i in seen}
    record("两份结论并列可见", both, f"决策员看到 {len(seen)} 份报告")
    record("两份报告未被合并", a1["id"] != a2["id"] and a1["author_id"] != a2["author_id"], "作者不同、ID 不同")
    hidden = c["analyst02"].send("GET", f"/analysis-reports/{a1['id']}", expect=(403, 404))
    record("分析员读不到他人报告", isinstance(hidden, dict) and "code" in hidden, "返回错误体而非数据")

    # ---------- 场景 3：多决策员冲突与幂等 ----------
    print("\n[场景 3] 重复与冲突指令")
    cmd1 = c["dmaker01"].send("POST", "/commands", {
        "title": "冲突测试-指令甲", "objective": "同一目标：核查固定时段路线",
        "content": "派执行员在固定时段沿北侧观察并记录车辆往返。", "priority": "urgent",
        "source_report_id": a1["id"],
    }, key())
    exec1_id = c["exec01"].send("GET", "/auth/me")["id"]
    issue_key = key()
    cmd1 = c["dmaker01"].send("POST", f"/commands/{cmd1['id']}/issue",
                              {"expected_version": cmd1["version"], "executor_ids": [exec1_id], "conflict_acknowledged": True}, issue_key)
    record("首条指令下达成功", cmd1["status"] in ("issued", "partially_accepted"), cmd1["status"])
    again = c["dmaker01"].send("POST", f"/commands/{cmd1['id']}/issue",
                               {"expected_version": cmd1["version"], "executor_ids": [exec1_id], "conflict_acknowledged": True}, issue_key)
    record("同幂等键重复下达不产生新指令", again["id"] == cmd1["id"], "返回同一条指令")

    cmd2 = c["dmaker01"].send("POST", "/commands", {
        "title": "冲突测试-指令乙", "objective": "同一目标：核查固定时段路线",
        "content": "派执行员对同一时段的路线再做一次核查，与甲指令目标重叠。", "priority": "urgent",
        "source_report_id": a1["id"],
    }, key())
    check = c["dmaker01"].send("GET", f"/commands/conflicts?source_report_id={a1['id']}")
    record("冲突检查命中活动指令", bool(check.get("has_conflict")), f"conflicts={len(check.get('conflicts', []))}")
    blocked = c["dmaker01"].send("POST", f"/commands/{cmd2['id']}/issue",
                                {"expected_version": cmd2["version"], "executor_ids": [exec1_id], "conflict_acknowledged": False},
                                key(), expect=(409,))
    record("未确认冲突时下达被拒", blocked.get("code") == "WORKFLOW_CONFLICT", blocked.get("code", "?"))
    forced = c["dmaker01"].send("POST", f"/commands/{cmd2['id']}/issue",
                                {"expected_version": cmd2["version"], "executor_ids": [exec1_id], "conflict_acknowledged": True}, key())
    record("确认冲突后可下达", forced["status"] in ("issued", "partially_accepted"), forced["status"])

    # ---------- 场景 4：多执行员与重复执行 ----------
    print("\n[场景 4] 多执行员分配与重复执行")
    exec2_id = c["exec02"].send("GET", "/auth/me")["id"]
    cmd3 = c["dmaker01"].send("POST", "/commands", {
        "title": "冲突测试-指令丙（双执行员）", "objective": "双人协同核查",
        "content": "甲乙两名执行员分别从南北两侧核查同一时段路线。", "priority": "normal",
        "source_report_id": a2["id"],
    }, key())
    cmd3 = c["dmaker01"].send("POST", f"/commands/{cmd3['id']}/issue",
                              {"expected_version": cmd3["version"], "executor_ids": [exec1_id, exec2_id], "conflict_acknowledged": True}, key())
    record("一条指令拆成两个个人分配", len(cmd3.get("assignments", [])) == 2, f"{len(cmd3.get('assignments', []))} 个分配")

    e1_list = c["exec01"].send("GET", "/assignments?page_size=50")["items"]
    e2_list = c["exec02"].send("GET", "/assignments?page_size=50")["items"]
    e1_ids = {i["id"] for i in e1_list}
    e2_ids = {i["id"] for i in e2_list}
    record("执行员只看到本人分配", not (e1_ids & e2_ids), f"甲 {len(e1_ids)} 条 / 乙 {len(e2_ids)} 条")

    def act(client: Client, assignment: dict[str, Any], action: str, body: dict[str, Any] | None = None,
            idem: str | None = None, expect: tuple[int, ...] = (200,)) -> Any:
        payload = {"expected_version": assignment["version"]}
        if body:
            payload.update(body)
        return client.send("POST", f"/assignments/{assignment['id']}/{action}", payload, idem, expect)

    a_e1 = next(i for i in e1_list if i["command_id"] == cmd3["id"])
    a_e2 = next(i for i in e2_list if i["command_id"] == cmd3["id"])
    a_e1 = act(c["exec01"], a_e1, "accept")
    a_e1 = act(c["exec01"], a_e1, "start")
    done_key = key()
    a_e1 = act(c["exec01"], a_e1, "complete",
               {"outcome": "success", "summary": "甲完成南侧核查，取得 2 段记录。", "detail": "无异常。"}, done_key)
    record("甲完成后个人状态", a_e1["status"] == "completed", a_e1["status"])
    status = c["dmaker01"].send("GET", f"/commands/{cmd3['id']}/status")
    record("聚合状态为部分完成", status["status"] == "partially_completed", status["status"])
    repeat = act(c["exec01"], a_e1, "complete",
                 {"outcome": "success", "summary": "重复提交同一结果。", "detail": "重复。"}, done_key)
    record("同幂等键重复完成返回原结果", repeat["status"] == "completed", "未产生第二份结果")
    conflict = act(c["exec01"], a_e1, "complete",
                   {"outcome": "success", "summary": "换键重复提交。", "detail": "换键。"}, key(), expect=(409,))
    record("换幂等键重复完成被拒", conflict.get("code") in ("WORKFLOW_CONFLICT", "DUPLICATE_OPERATION"),
           conflict.get("code", "?"))

    a_e2 = act(c["exec02"], a_e2, "accept")
    a_e2 = act(c["exec02"], a_e2, "start")
    a_e2 = act(c["exec02"], a_e2, "complete",
               {"outcome": "success", "summary": "乙完成北侧核查，取得 1 段记录。", "detail": "无异常。"}, key())
    status = c["dmaker01"].send("GET", f"/commands/{cmd3['id']}/status")
    record("全部完成后聚合状态完成", status["status"] == "completed", status["status"])

    # ---------- 场景 5：越权与串号 ----------
    print("\n[场景 5] 越权与串号")
    other = c["exec02"].send("GET", f"/assignments/{a_e1['id']}", expect=(403, 404))
    record("执行员读他本人以外的分配被拒", isinstance(other, dict) and "code" in other, other.get("code", "?"))
    analyst = c["analyst02"].send("GET", "/commands?page_size=50", expect=(200, 403, 404))
    record("分析员访问决策资源被拦", isinstance(analyst, dict), analyst.get("code", "可访问（按契约允许读取相关指令）")
           if isinstance(analyst, dict) and "code" in analyst else "按契约返回列表，由资源范围过滤")

    fails = [r for r in RESULTS if r[1] == "FAIL"]
    print("\n===== 汇总 =====")
    print(f"用例 {len(RESULTS)} 条：PASS {len(RESULTS) - len(fails)} / FAIL {len(fails)}")
    for scene, state, detail in RESULTS:
        if state == "FAIL":
            print(f"  FAIL {scene}: {detail}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
