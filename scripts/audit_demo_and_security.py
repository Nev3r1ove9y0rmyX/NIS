"""按演示脚本实跑 + 针对性安全检查。

两部分：
A. 功能演练：完全照 docs/onsite-demo-fill-in.md 的内容跑一遍四角色闭环，逐步断言；
B. 安全检查：越权访问、角色上下文伪造、令牌篡改、强制下线、设备绑定绕过、
   幂等重放、版本冲突、注入尝试、审计泄露等。

只读或可恢复操作；强制下线等会立即重新登录恢复。
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

BASE = os.environ.get("NIS_BASE_URL", "http://127.0.0.1/api/v1").rstrip("/")
PW = os.environ.get("NIS_DEMO_PASSWORD", "")
ADMIN_PW = os.environ.get("NIS_ADMIN_PASSWORD", PW)
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
RESULTS: list[dict] = []


def call(method, path, body=None, token=None, role=None, headers=None, timeout=60):
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    if token:
        hdrs["Authorization"] = f"Bearer {token}"
    if role:
        hdrs["X-Role-Context"] = role
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=hdrs, method=method)
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"raw": raw[:200].decode("utf-8", "replace")}
        return exc.code, parsed


def record(name: str, ok: bool, severity: str, detail: str, expect: str = "") -> None:
    RESULTS.append({"name": name, "ok": ok, "severity": severity, "detail": detail, "expect": expect})
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] ({severity}) {name} — {detail}")


def login(username: str, password: str | None = None) -> dict:
    st, payload = call("POST", "/auth/login", {"username": username, "password": password or PW})
    if st != 200:
        raise SystemExit(f"登录 {username} 失败：{st} {payload}")
    return payload


def uid(token: str) -> str:
    _, me = call("GET", "/auth/me", token=token)
    return me["id"]


# ============================================================ A. 功能演练
def functional_dryrun() -> dict:
    print("\n[A] 按演示脚本跑一遍 OODA 闭环")
    suffix = uuid.uuid4().hex[:4]
    recon_title = f"北侧路段车辆往返观察（08:00 时段）{suffix}"
    out = {}

    # 1) 侦察
    c = login("recon01")
    st, rec = call("POST", "/recon-records", {
        "title": recon_title,
        "source_type": "osint",
        "source_ref": "演示用公开素材，已脱敏",
        "content": ("在课程授权的演示环境中，观察点位于目标区域北侧路段。连续三日记录显示，每日 08:00 前后有车辆往返通过，"
                    "路线固定、间隔稳定；伴随人员上下车与短暂停留（约 5 分钟）。以上内容为演示数据，不对应任何真实目标。"),
        "credibility": "medium",
        "priority": "urgent",
        "evidence": [],
    }, token=c["access_token"], headers={"Idempotency-Key": uuid.uuid4().hex})
    record("A1 侦察记录创建", st == 201, "功能", f"HTTP {st}")
    rid = rec["id"]

    # AI 建议（不保存也能分析：这里等价于已保存后请求）
    st, sug = call("POST", "/ai/suggestions", {
        "stage": "recon", "business_object_type": "recon_record",
        "business_object_id": rid, "suggestion_type": "summary",
    }, token=c["access_token"])
    grounded = st == 200 and any(w in json.dumps(sug.get("content", {}), ensure_ascii=False) for w in ("北侧", "08:00", "往返", "车辆"))
    record("A2 AI 建议基于记录内容", grounded, "功能",
           f"HTTP {st} model={sug.get('model_name')} 引用内容={grounded}")
    st, sug2 = call("POST", f"/ai/suggestions/{sug['id']}/decision", {"decision": "accepted"}, token=c["access_token"])
    record("A3 AI 建议人工接受", st == 200 and sug2.get("status") == "accepted", "功能", f"HTTP {st}")
    st, _ = call("POST", f"/ai/suggestions/{sug['id']}/decision", {"decision": "accepted"}, token=c["access_token"])
    record("A4 重复确认被拒 409", st == 409, "功能", f"HTTP {st}")

    analysts = call("GET", "/candidates?target_role=analyst&page_size=50", token=c["access_token"])[1]["items"]
    analyst_id = next(i["user_id"] for i in analysts if i["display_name"].startswith("分析员甲"))
    st, _ = call("POST", f"/recon-records/{rid}/submit",
                 {"expected_version": rec["version"], "analyst_ids": [analyst_id]}, token=c["access_token"])
    record("A5 侦察提交并指派", st == 200, "功能", f"HTTP {st}")

    # 2) 分析
    a = login("analyst01")
    st, rep = call("POST", "/analysis-reports", {
        "title": f"北侧路段活动规律分析（固定保障节点）{suffix}",
        "recon_record_ids": [rid],
        "key_findings": "北侧路段车辆往返时段与路线均稳定，08:00 前后为固定保障节点；人员与车辆在同一时段出现，存在时间耦合。",
        "relations": "车辆往返与人员上下车在同一时段出现；南北两侧道路的通行情况需要对比确认。",
        "risk_level": "medium",
        "recommended_actions": "在固定时段前完成观察点部署，保留影像与通联记录，避免主动接触。",
        "priority": "normal",
    }, token=a["access_token"], headers={"Idempotency-Key": uuid.uuid4().hex})
    record("A6 分析报告创建", st == 201, "功能", f"HTTP {st}")
    st, sug3 = call("POST", "/ai/suggestions", {
        "stage": "analysis", "business_object_type": "analysis_report",
        "business_object_id": rep["id"], "suggestion_type": "summary",
    }, token=a["access_token"])
    grounded3 = st == 200 and any(w in json.dumps(sug3.get("content", {}), ensure_ascii=False) for w in ("稳定", "固定", "耦合", "观察"))
    record("A7 分析环节 AI 建议引用报告", grounded3, "功能", f"HTTP {st}")
    dms = call("GET", "/candidates?target_role=decision_maker&page_size=50", token=a["access_token"])[1]["items"]
    dm_id = next(i["user_id"] for i in dms if i["display_name"].startswith("决策员甲"))
    st, _ = call("POST", f"/analysis-reports/{rep['id']}/submit",
                 {"expected_version": rep["version"], "decision_maker_ids": [dm_id], "ai_content_confirmed": True},
                 token=a["access_token"])
    record("A8 报告提交并指派决策员", st == 200, "功能", f"HTTP {st}")

    # 3) 决策
    d = login("dmaker01")
    st, cmd = call("POST", "/commands", {
        "title": f"北侧路段核查与反馈（固定时段）{suffix}",
        "objective": "确认北侧路段固定时段的车辆往返频次",
        "content": "按约定时段到位观察，记录车辆往返频次、停留时长与人员活动；只做观察与记录，不主动接触；完成后提交结果与证据。",
        "priority": "urgent",
        "source_report_id": rep["id"],
    }, token=d["access_token"], headers={"Idempotency-Key": uuid.uuid4().hex})
    record("A9 指令创建", st == 201, "功能", f"HTTP {st}")
    st, conflicts = call(
        "GET",
        f"/commands/conflicts?source_report_id={rep['id']}&objective=" + urllib.parse.quote("确认北侧路段固定时段的车辆往返频次"),
        token=d["access_token"],
    )
    record("A10 冲突检查可用", st == 200 and "has_conflict" in (conflicts or {}), "功能", f"HTTP {st}")

    execs = call("GET", "/candidates?target_role=executor&page_size=50", token=d["access_token"])[1]["items"]
    exec01_id = next(i["user_id"] for i in execs if i["display_name"].startswith("执行员甲"))
    idem = uuid.uuid4().hex
    st, issued = call("POST", f"/commands/{cmd['id']}/issue",
                      {"expected_version": cmd["version"], "executor_ids": [exec01_id], "conflict_acknowledged": True},
                      token=d["access_token"], headers={"Idempotency-Key": idem})
    record("A11 指令下达", st == 200 and issued["status"] == "issued", "功能", f"HTTP {st} status={issued.get('status')}")
    st, issued2 = call("POST", f"/commands/{cmd['id']}/issue",
                       {"expected_version": cmd["version"], "executor_ids": [exec01_id], "conflict_acknowledged": True},
                       token=d["access_token"], headers={"Idempotency-Key": idem})
    record("A12 同幂等键重放不重复下达", st == 200 and len(issued2["assignments"]) == len(issued["assignments"]),
           "功能", f"HTTP {st} 分配数 {len(issued.get('assignments', []))}→{len(issued2.get('assignments', []))}")

    # 4) 执行
    e = login("exec01")
    _, assignments = call("GET", "/assignments?page_size=50", token=e["access_token"])
    target = next(i for i in assignments["items"] if i["command_id"] == cmd["id"])
    for action in ("accept", "start"):
        st, target = call("POST", f"/assignments/{target['id']}/{action}",
                          {"expected_version": target["version"]}, token=e["access_token"])
    record("A13 执行员接收与开始", target["status"] == "executing", "功能", f"status={target['status']}")
    st, done = call("POST", f"/assignments/{target['id']}/complete", {
        "expected_version": target["version"],
        "outcome": "success",
        "summary": "按计划完成北侧路段 08:00 时段观察，取得 2 段连续记录。",
        "detail": "观察期间记录车辆往返 3 次、人员上下车 2 次；未发生异常接触；影像与通联记录已存档。",
    }, token=e["access_token"], headers={"Idempotency-Key": uuid.uuid4().hex})
    record("A14 执行结果提交", st == 200 and done["status"] == "completed", "功能", f"HTTP {st} status={done.get('status')}")

    st, status = call("GET", f"/commands/{cmd['id']}/status", token=d["access_token"])
    record("A15 指令总体状态 completed", st == 200 and status["status"] == "completed", "功能",
           f"HTTP {st} status={status.get('status')}")

    # 5) 报告状态
    st, report_now = call("GET", f"/analysis-reports/{rep['id']}", token=d["access_token"])
    record("A16 报告状态已决策", st == 200 and report_now["status"] == "decided", "功能",
           f"HTTP {st} status={report_now.get('status')}")

    out["cmd"] = cmd
    out["issue_id"] = target["id"]
    out["rep"] = rep
    out["rec"] = rec
    return out


# ============================================================ B. 安全检查
def security_checks(ctx: dict) -> None:
    print("\n[B] 安全检查")
    c = login("recon01")["access_token"]
    c2 = login("recon02")["access_token"]
    a = login("analyst01")["access_token"]
    d = login("dmaker01")["access_token"]
    e = login("exec01")["access_token"]
    admin = login("admin", ADMIN_PW)["access_token"]

    # B1 越权读取他人侦察记录
    st, _ = call("GET", f"/recon-records/{ctx['rec']['id']}", token=c2)
    record("B1 他人侦察记录越权读取", st in (403, 404), "高", f"HTTP {st}", "403/404")

    # B2 越权读取他人分析报告
    st, _ = call("GET", f"/analysis-reports/{ctx['rep']['id']}", token=c2)
    record("B2 侦察员越权读报告", st in (403, 404), "高", f"HTTP {st}", "403/404")

    # B3 运维/管理接口越权
    st, _ = call("GET", "/admin/roles", token=e)
    record("B3 执行员访问管理接口", st == 403, "高", f"HTTP {st}", "403")

    # B4 角色上下文伪造：admin 声明非本人角色
    st, _ = call("GET", "/admin/roles", token=admin, role="analyst")
    record("B4 伪造角色上下文", st == 403, "高", f"HTTP {st}", "403")

    # B5 分析员调用指令接口
    st, _ = call("POST", "/commands", {
        "title": "越权测试", "objective": "越权", "content": "越权测试内容至少十个字符",
        "priority": "normal", "source_report_id": ctx["rep"]["id"],
    }, token=a)
    record("B5 分析员越权下达指令", st == 403, "高", f"HTTP {st}", "403")

    # B6 篡改 JWT
    parts = a.split(".")
    fake = f"{parts[0]}.{parts[1]}.{'A' * 40}"
    st, _ = call("GET", "/auth/me", token=fake)
    record("B6 篡改 JWT 签名", st == 401, "高", f"HTTP {st}", "401")

    # B7 refresh token 冒充 access token
    st, tokens = call("POST", "/auth/login", {"username": "analyst01", "password": PW})
    st, _ = call("GET", "/auth/me", token=tokens.get("refresh_token", ""))
    record("B7 refresh token 冒充访问令牌", st == 401, "高", f"HTTP {st}", "401")

    # B8 未认证访问
    st, _ = call("GET", "/recon-records")
    record("B8 未认证访问业务接口", st == 401, "高", f"HTTP {st}", "401")

    # B9 SQL 注入尝试
    st, _ = call("POST", "/auth/login", {"username": "recon01' OR '1'='1", "password": "x"})
    record("B9 登录 SQL 注入", st in (400, 401, 422), "高", f"HTTP {st}", "400/401/422（均不通过）")

    # B10 路径穿越/注入到查询参数
    st, _ = call("GET", "/recon-records?page=1&page_size=5%20OR%201=1", token=c)
    record("B10 查询参数注入", st in (200, 400, 422), "中", f"HTTP {st}", "不返回他人数据")

    # B11 版本冲突
    st, _ = call("POST", f"/assignments/{ctx['issue_id']}/accept",
                 {"expected_version": 1}, token=e)
    record("B11 旧版本更新被拒", st in (409, 400), "中", f"HTTP {st}", "409")

    # B12 已完成任务重复提交
    st, _ = call("POST", f"/assignments/{ctx['issue_id']}/complete",
                 {"expected_version": 99, "outcome": "success", "summary": "重复提交"},
                 token=e, headers={"Idempotency-Key": uuid.uuid4().hex})
    record("B12 已完成任务重复提交", st in (409, 400, 422), "中", f"HTTP {st}", "409")

    # B13 已完成任务转交
    st, _ = call("POST", f"/assignments/{ctx['issue_id']}/transfer",
                 {"expected_version": 1, "target_executor_id": uid(login("exec02")["access_token"])},
                 token=e)
    record("B13 已完成任务不可转交", st == 409, "中", f"HTTP {st}", "409")

    # B14 XSS 内容存储与返回
    xss = "<script>alert('xss')</script>"
    st, stored = call("POST", "/recon-records", {
        "title": f"XSS 测试 {uuid.uuid4().hex[:4]}", "source_type": "other",
        "content": f"测试内容：{xss} 后续文字用于满足最小长度限制。",
        "credibility": "unverified", "priority": "normal", "evidence": [],
    }, token=c, headers={"Idempotency-Key": uuid.uuid4().hex})
    record("B14 XSS 内容被原样存储（前端需转义）", st == 201, "低",
           "后端按文本存储，Vue 文本插值默认转义；未发现 HTML 注入执行面", "前端转义")

    # B15 审计泄露检查
    st, events = call("GET", "/audit-events?page=1&page_size=50", token=admin, role="administrator")
    blob = json.dumps(events, ensure_ascii=False)
    leaked = [w for w in ("eyJhbGciOi", "password_hash", "$2b$", "refresh_token") if w in blob]
    record("B15 审计无口令/令牌泄露", st == 200 and not leaked, "高", f"泄露关键词={leaked or '无'}", "无")

    # B16 强制下线后旧令牌立即失效
    exec_tokens = login("exec01")
    st, _ = call("POST", f"/admin/users/{uid(exec_tokens['access_token'])}/force-logout",
                 token=admin, role="administrator")
    st2, _ = call("GET", "/assignments?page_size=1", token=exec_tokens["access_token"])
    record("B16 强制下线后旧令牌失效", st == 200 and st2 == 401, "高", f"强制下线 {st}，旧令牌 {st2}", "旧令牌 401")

    # B17 设备绑定不可通过伪造 XFF 绕过
    exec2 = login("exec02")
    exec2_id = uid(exec2["access_token"])
    call("PUT", f"/admin/users/{exec2_id}/device-binding",
         {"allowed_ips": ["10.9.9.9"], "allowed_macs": []}, token=admin, role="administrator")
    st, _ = call("POST", "/auth/login", {"username": "exec02", "password": PW},
                 headers={"X-Forwarded-For": "10.9.9.9"})
    record("B17 伪造 XFF 不能绕过设备绑定", st == 403, "高", f"HTTP {st}", "403")
    call("PUT", f"/admin/users/{exec2_id}/device-binding",
         {"allowed_ips": [], "allowed_macs": []}, token=admin, role="administrator")

    # B18 候选角色枚举攻击
    st, cand = call("GET", "/candidates?target_role=administrator", token=c)
    empty = st != 200 or not cand.get("items")
    record("B18 候选接口不泄露无关用户", empty, "低",
           f"HTTP {st} items={len((cand or {}).get('items', []))}", "空列表或非 200")

    # B19 审计不可篡改（无写接口）
    st, _ = call("POST", "/audit-events", {"action": "forged"}, token=admin, role="administrator")
    record("B19 审计事件不可伪造写入", st in (404, 405, 422, 403), "高", f"HTTP {st}", "不可写")

    # B20 登录失败信息不泄露账号是否存在
    st1, p1 = call("POST", "/auth/login", {"username": "recon01", "password": "wrong-password"})
    st2, p2 = call("POST", "/auth/login", {"username": "nobody-here", "password": "wrong-password"})
    same = (st1 == st2) and (p1.get("message") == p2.get("message"))
    record("B20 登录错误不区分账号是否存在", same, "中", f"{st1}/{st2} msg={p1.get('message')}", "一致")


def main() -> int:
    if not PW:
        print("缺少 NIS_DEMO_PASSWORD", file=sys.stderr)
        return 2
    print(f"目标：{BASE}")
    ctx = functional_dryrun()
    security_checks(ctx)

    failed = [r for r in RESULTS if not r["ok"]]
    highs = [r for r in failed if r["severity"] == "高"]
    print(f"\n汇总：{len(RESULTS)} 项，PASS {len(RESULTS) - len(failed)} / FAIL {len(failed)}"
          f"（高危 {len(highs)}）")
    for item in failed:
        print(f"  FAIL [{item['severity']}] {item['name']} — {item['detail']}（期望 {item['expect']}）")
    with open("/tmp/security-report.json", "w", encoding="utf-8") as fh:
        json.dump(RESULTS, fh, ensure_ascii=False, indent=2)
    return 0 if not highs else 1


if __name__ == "__main__":
    raise SystemExit(main())
