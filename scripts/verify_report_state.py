"""验证：下达指令后报告状态是否从 assigned 流转到 decided（含 under_decision 中间态）。

流程：
1. dmaker01 登录，取一份指派给自己的 assigned 报告；
2. 基于该报告起草指令 → 期望报告变 under_decision；
3. 下达指令给 exec01 → 期望报告变 decided 且 command_id 非空；
4. 打印报告状态变化。
"""

import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("NIS_BASE_URL", "http://127.0.0.1/api/v1").rstrip("/")
DEMO_PW = os.environ.get("NIS_DEMO_PASSWORD", "")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, body=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw[:200].decode("utf-8", "replace")}
        return exc.code, parsed


def main() -> int:
    if not DEMO_PW:
        print("缺少 NIS_DEMO_PASSWORD", file=sys.stderr)
        return 2

    _, dm = call("POST", "/auth/login", {"username": "dmaker01", "password": DEMO_PW})
    dm_token = dm["access_token"]
    _, dm_me = call("GET", "/auth/me", token=dm_token)
    dm_id = dm_me["id"]

    _, reports = call("GET", "/analysis-reports?page=1&page_size=20&status=assigned", token=dm_token)
    candidates = [r for r in reports.get("items", []) if dm_id in (r.get("decision_maker_ids") or [])]
    if not candidates:
        candidates = reports.get("items", [])
    if not candidates:
        print("没有可用的 assigned 报告")
        return 1
    report = candidates[0]
    rid = report["id"]
    print(f"选中报告 {report['report_no']} 当前状态 = {report['status']}")

    # 起草指令
    st, command = call("POST", "/commands", {
        "title": "状态回写验证-指令",
        "objective": "验证报告状态回写",
        "content": "用于验证下达指令后报告状态从 assigned 流转到 decided。",
        "priority": "normal",
        "source_report_id": rid,
    }, token=dm_token)
    if st not in (200, 201):
        print("起草指令失败", st, command)
        return 1
    _, after_draft = call("GET", f"/analysis-reports/{rid}", token=dm_token)
    print(f"起草后报告状态 = {after_draft.get('status')}（期望 under_decision）")

    _, exec_login = call("POST", "/auth/login", {"username": "exec01", "password": DEMO_PW})
    _, exec_me = call("GET", "/auth/me", token=exec_login["access_token"])

    st, issued = call("POST", f"/commands/{command['id']}/issue", {
        "expected_version": command["version"],
        "executor_ids": [exec_me["id"]],
        "conflict_acknowledged": True,
    }, token=dm_token)
    if st not in (200, 201):
        print("下达指令失败", st, issued)
        return 1
    _, after_issue = call("GET", f"/analysis-reports/{rid}", token=dm_token)
    print(f"下达后报告状态 = {after_issue.get('status')}（期望 decided）")
    print(f"报告上的 command_id = {after_issue.get('command_id')}")

    ok = after_draft.get("status") == "under_decision" and after_issue.get("status") == "decided"
    print("\n结论：", "通过" if ok else "未通过")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
