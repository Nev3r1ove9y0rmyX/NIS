"""清理演示数据：作废测试指令、替换不当文案、新增一条中性演示链。

做三件事（均可在部署环境直接运行）：
1. 执行员把"测试性质且内容不当"的待接收指令**拒绝**掉（走接口，留审计，不删数据）；
2. 对历史测试记录里的不当文字做**文本清理**（只改文案，不改状态/不删行）；
3. 用四个账号新建一条**中性文案**的完整 OODA 链（侦察→分析→指令→执行），
   让演示列表顶部是干净数据，且能展示 completed 闭环。

用法（在 Ubuntu 的 ~/NIS 下）：
    export NIS_BASE_URL=http://127.0.0.1/api/v1
    export NIS_DEMO_PASSWORD=***
    python3 scripts/clean_demo_data.py
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("NIS_BASE_URL", "http://127.0.0.1/api/v1").rstrip("/")
DEMO_PW = os.environ.get("NIS_DEMO_PASSWORD", "")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class ApiError(RuntimeError):
    def __init__(self, status: int, payload) -> None:
        super().__init__(f"HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


def call(method: str, path: str, body=None, token: str | None = None, idem: bool = False):
    headers = {"Accept": "application/json"}
    if idem:
        headers["Idempotency-Key"] = os.urandom(16).hex()
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw[:200].decode("utf-8", "replace")
        raise ApiError(exc.code, parsed) from exc


def login(username: str) -> str:
    payload = call("POST", "/auth/login", {"username": username, "password": DEMO_PW})
    return payload["access_token"]


def mysql_exec(sql: str) -> None:
    """在部署主机上通过 docker exec 执行 SQL（仅用于演示文案清理）。"""

    env_file = pathlib.Path.home() / "NIS" / ".env"
    root_pw = ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith("MYSQL_ROOT_PASSWORD="):
            root_pw = line.split("=", 1)[1].strip()
            break
    env = dict(os.environ, MYSQL_PWD=root_pw)
    proc = subprocess.run(
        ["docker", "exec", "-i", "-e", f"MYSQL_PWD={root_pw}", "nis-mysql-1",
         "mysql", "-uroot", "-e", sql],
        capture_output=True, text=True, env=env, check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"SQL 执行失败：{proc.stderr.strip()}")


TEXT_CLEANUP = [
    (
        "不当文案·分析报告 1",
        "UPDATE nis_analysis.analysis_reports SET "
        "title='样例：北侧路段车辆往返', "
        "key_findings='目标车辆每日 08:00 前后沿北侧路段往返，路线与时段均较固定。' "
        "WHERE report_no='RPT-20261103-0002';",
    ),
    (
        "不当文案·分析报告 2",
        "UPDATE nis_analysis.analysis_reports SET "
        "title='样例：南侧路段通行情况', "
        "key_findings='南侧路段同时段出现车辆通行，需与北侧观察记录对比确认。' "
        "WHERE report_no='RPT-20261103-0001';",
    ),
    (
        "垃圾文案·侦察记录 1",
        "UPDATE nis_recon.recon_records SET "
        "title='样例：北侧路段观察', "
        "content='目标车辆每日 08:00 前后沿北侧路段往返，观察持续约 2 小时。' "
        "WHERE record_no='REC-20261103-0001';",
    ),
    (
        "垃圾文案·侦察记录 2",
        "UPDATE nis_recon.recon_records SET "
        "title='样例：南侧路段观察', "
        "content='南侧路段同时段出现车辆通行，需与北侧观察记录对比。' "
        "WHERE record_no='REC-20261103-0002';",
    ),
    (
        "不当文案·作废指令",
        "UPDATE nis_decision.commands SET "
        "title='样例：北侧路段复查（作废）', "
        "content='（测试数据，已作废，不作为业务指令下发）' "
        "WHERE command_no='CMD-20261103-0002';",
    ),
    (
        "泛化文案·指令",
        "UPDATE nis_decision.commands SET "
        "title='样例：北侧路段核查与反馈', "
        "content='沿北侧路段核查车辆往返频次与时段，完成后提交结果与证据。' "
        "WHERE command_no='CMD-20261103-0001';",
    ),
]


def reject_test_assignment() -> str:
    exec_token = login("exec01")
    assignments = call("GET", "/assignments?page_size=50", token=exec_token)["items"]
    for item in assignments:
        title = item.get("command_title_snapshot") or ""
        content = item.get("command_content_snapshot") or ""
        if item["status"] == "pending" and ("杀" in content or "老⑧" in content or "杀" in title):
            call(
                "POST",
                f"/assignments/{item['id']}/reject",
                {"expected_version": item["version"], "reason": "测试数据作废，不作为业务指令接收"},
                token=exec_token,
            )
            return f"{item['id'][:8]}（{title}）"
    return "（未发现需作废的待接收指令）"


def seed_clean_chain() -> dict[str, str]:
    recon = login("recon01")
    analyst_token_early = login("analyst01")
    analyst_me = call("GET", "/auth/me", token=analyst_token_early)
    dm_token_early = login("dmaker01")
    dm_me = call("GET", "/auth/me", token=dm_token_early)
    exec_token_early = login("exec01")
    exec_me = call("GET", "/auth/me", token=exec_token_early)
    record = call("POST", "/recon-records", {
        "title": "样例演示：北侧路段日活动观察",
        "source_type": "osint",
        "source_ref": "演示脚本（中性文案）",
        "content": "在课程授权演示环境中，观察到目标车辆每日 08:00 前后沿北侧路段往返，路线相对固定。",
        "credibility": "high",
        "priority": "normal",
        "evidence": [],
    }, token=recon, idem=True)
    call("POST", f"/recon-records/{record['id']}/submit",
         {"expected_version": record["version"], "analyst_ids": [analyst_me["id"]]}, token=recon)

    analyst = analyst_token_early
    report = call("POST", "/analysis-reports", {
        "title": "样例演示：北侧路段活动规律分析",
        "recon_record_ids": [record["id"]],
        "key_findings": "北侧路段车辆往返时段与路线均稳定，具备固定保障节点特征。",
        "relations": "人员与车辆在同一时段出现，存在时间耦合。",
        "risk_level": "medium",
        "recommended_actions": "在固定时段前完成观察点部署，并保留影像证据。",
        "priority": "normal",
    }, token=analyst, idem=True)
    call("POST", f"/analysis-reports/{report['id']}/submit",
         {"expected_version": report["version"], "decision_maker_ids": [dm_me["id"]],
          "ai_content_confirmed": True}, token=analyst)

    dm = dm_token_early
    command = call("POST", "/commands", {
        "title": "样例演示：北侧路段核查与反馈",
        "objective": "确认北侧路段车辆往返频次与固定时段",
        "content": "按约定时段到位观察，记录车辆往返频次，完成后提交结果与证据。",
        "priority": "normal",
        "source_report_id": report["id"],
    }, token=dm, idem=True)
    call("POST", f"/commands/{command['id']}/issue",
         {"expected_version": command["version"], "executor_ids": [exec_me["id"]],
          "conflict_acknowledged": True}, token=dm, idem=True)

    exec_token = exec_token_early
    assignments = call("GET", "/assignments?page_size=50", token=exec_token)["items"]
    target = next(item for item in assignments if item["command_id"] == command["id"])
    for action in ("accept", "start"):
        target = call("POST", f"/assignments/{target['id']}/{action}",
                      {"expected_version": target["version"]}, token=exec_token)
    target = call("POST", f"/assignments/{target['id']}/complete", {
        "expected_version": target["version"],
        "outcome": "success",
        "summary": "按计划完成北侧路段观察，取得 2 段连续记录。",
        "detail": "观察期间未发生异常接触。",
    }, token=exec_token, idem=True)

    status_view = call("GET", f"/commands/{command['id']}/status", token=dm)
    return {
        "record": record["record_no"],
        "report": report["report_no"],
        "command": command["command_no"],
        "command_aggregate": status_view["status"],
    }


def show_state() -> None:
    recon = login("recon01")
    exec_token = login("exec01")
    dm = login("dmaker01")
    reports = call("GET", "/analysis-reports?page=1&page_size=6", token=dm)["items"]
    print("\n最新报告（决策员视角）：")
    for item in reports:
        print(f"  {item['report_no']}  {item['status']:<14} {item['title']}")
    assignments = call("GET", "/assignments?page_size=6", token=exec_token)["items"]
    print("\n执行员最新待办：")
    for item in assignments:
        print(f"  {item['command_title_snapshot']:<28} {item['status']}")


def main() -> int:
    if not DEMO_PW:
        print("缺少 NIS_DEMO_PASSWORD", file=sys.stderr)
        return 2

    print("1) 作废内容不当的测试指令（走接口，留审计）")
    print("   已拒绝：", reject_test_assignment())

    print("\n2) 清理历史测试文案（只改文字，不动状态）")
    for label, sql in TEXT_CLEANUP:
        mysql_exec(sql)
        print("   已清理：", label)

    print("\n3) 新增一条中性文案的完整 OODA 链")
    trace = seed_clean_chain()
    for key, value in trace.items():
        print(f"   {key} = {value}")

    show_state()
    ok = trace.get("command_aggregate") == "completed"
    print("\n结论：", "通过（新链路 completed）" if ok else "链路未完成，请检查")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
