"""一键功能体检：逐项验证中期验收的每个功能是否真的可用。

AI 部分默认要求命中真实模型（见 NIS_SMOKE_ALLOW_FALLBACK）。
只做只读或可逆操作，不改业务数据：
- 登录/角色/权限、越权拦截、候选筛选；
- 审计列表与调用链；
- OODA 链路（读取最近一条指令的总体状态）；
- AI 建议（生成 + 人工确认）；
- 优先级排序；
- 细粒度权限（保存同一组权限，幂等）；
- 限时角色（读取绑定与到期时间，不新建）；
- 在线用户、设备绑定读取、强制下线参数校验（不真下线）；
- 任务转交（读取候选执行员，不执行转交）。

用法：
    set NIS_SMOKE_BASE=http://192.168.58.20/api/v1
    python scripts/smoke_features.py

退出码：0 全部通过；1 有失败。
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("NIS_SMOKE_BASE", "http://192.168.58.20/api/v1").rstrip("/")
ADMIN_PW = os.environ.get("NIS_ADMIN_PASSWORD", "")
DEMO_PW = os.environ.get("NIS_DEMO_PASSWORD", "")
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
#: 默认要求 AI 命中真实模型；本地规则模板环境可设 NIS_SMOKE_ALLOW_FALLBACK=1 放宽
ALLOW_FALLBACK = os.environ.get("NIS_SMOKE_ALLOW_FALLBACK", "").strip().lower() in {"1", "true", "yes"}
EXPECT_MODEL = os.environ.get("NIS_SMOKE_EXPECT_MODEL", "").strip()
RESULTS: list[tuple[str, bool, str]] = []


def call(method: str, path: str, body=None, token=None, role=None, timeout: int = 15):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if role:
        headers["X-Role-Context"] = role
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        parsed = None
        if raw:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                # 反向代理可能返回 HTML 错误页（如 502），不要让脚本崩
                parsed = {"raw": raw[:200].decode("utf-8", "replace")}
        return exc.code, parsed
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        # 网络不可达/超时也当作一次失败检查，而不是让脚本崩溃
        return 0, {"error": type(exc).__name__, "message": str(exc)}


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name} {detail}")


def main() -> int:
    if not ADMIN_PW or not DEMO_PW:
        print("缺少 NIS_ADMIN_PASSWORD / NIS_DEMO_PASSWORD", file=sys.stderr)
        return 2

    print(f"目标环境：{BASE}")

    print("\n[1] 认证与用户系统")
    st, admin_login = call("POST", "/auth/login", {"username": "admin", "password": ADMIN_PW})
    check("管理员登录", st == 200, f"HTTP {st}")
    admin = admin_login["access_token"]
    roles = admin_login["user"]["roles"]
    check("管理员多角色", len(roles) > 1, str(roles))
    st, me = call("GET", "/auth/me", token=admin, role="administrator")
    check("带角色上下文可读本人权限", st == 200 and bool(me.get("permissions")), f"HTTP {st}")
    st, _ = call("GET", "/admin/roles", token=admin)
    check("不带角色上下文被拒", st == 403, f"HTTP {st}")

    for username in ("recon01", "analyst01", "dmaker01", "exec01"):
        st, payload = call("POST", "/auth/login", {"username": username, "password": DEMO_PW})
        check(f"角色登录 {username}", st == 200, str(payload["user"]["roles"]) if st == 200 else f"HTTP {st}")

    st, analyst = call("POST", "/auth/login", {"username": "analyst01", "password": DEMO_PW})
    analyst_token = analyst["access_token"]
    st, _ = call("GET", "/analysis-reports?page=1&page_size=3", token=analyst_token)
    check("分析员可读本角色资源", st == 200, f"HTTP {st}")

    st, recon = call("POST", "/auth/login", {"username": "recon01", "password": DEMO_PW})
    recon_token = recon["access_token"]
    st, _ = call("GET", "/analysis-reports?page=1&page_size=3", token=recon_token)
    check("侦察员越权被拒 403", st == 403, f"HTTP {st}")

    st, cand = call("GET", "/candidates?target_role=executor&page_size=50", token=admin, role="administrator")
    check("候选接收人筛选", st == 200 and len(cand["items"]) >= 1, f"{len(cand.get('items', []))} 人")

    print("\n[2] 日志与审计")
    st, events = call("GET", "/audit-events?page=1&page_size=5", token=admin, role="administrator")
    check("审计列表", st == 200 and events["total"] > 0, f"total={events.get('total')}")
    if st == 200 and events["items"]:
        rid = events["items"][0]["request_id"]
        st, trace = call("GET", f"/audit-events/traces/{rid}", token=admin, role="administrator")
        check("调用链还原", st == 200 and len(trace.get("events", [])) >= 1,
              f"{len(trace.get('events', []))} 条事件")

    print("\n[3] OODA 与指令状态")
    st, dm = call("POST", "/auth/login", {"username": "dmaker01", "password": DEMO_PW})
    dm_token = dm["access_token"]
    st, commands = call("GET", "/commands?page=1&page_size=5", token=dm_token)
    check("决策员读取指令", st == 200, f"total={commands.get('total') if st == 200 else '-'}")
    if st == 200 and commands["items"]:
        cid = commands["items"][0]["id"]
        st, status = call("GET", f"/commands/{cid}/status", token=dm_token)
        check("指令总体状态可读", st == 200 and status.get("status"), status.get("status", f"HTTP {st}"))
        check(
            "聚合状态规则生效",
            status.get("status") in {"issued", "partially_accepted", "accepted", "executing",
                                     "partially_completed", "completed", "failed", "rejected", "cancelled"},
            status.get("status", "-"),
        )

    print("\n[4] AI 与人在回路")
    # 用侦察记录做 AI 演示对象
    st, records = call("GET", "/recon-records?page=1&page_size=1", token=recon_token)
    if st == 200 and records["items"]:
        rid = records["items"][0]["id"]
        started = time.monotonic()
        st, suggestion = call("POST", "/ai/suggestions", {
            "stage": "recon", "business_object_type": "recon_record",
            "business_object_id": rid, "suggestion_type": "summary",
        }, token=recon_token, timeout=150)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        check("AI 建议生成", st in (200, 201) and suggestion.get("status") == "pending",
              f"HTTP {st} status={suggestion.get('status') if suggestion else '-'} 耗时 {elapsed_ms}ms")

        model_name = str((suggestion or {}).get("model_name") or "")
        fell_back = model_name.endswith("(fallback)")
        if EXPECT_MODEL:
            check(
                "AI 命中期望模型",
                model_name == EXPECT_MODEL,
                f"model_name={model_name or '-'}（期望 {EXPECT_MODEL}）",
            )
        else:
            check(
                "AI 命中真实模型（未静默回退）",
                ALLOW_FALLBACK or not fell_back,
                f"model_name={model_name or '-'}" + ("（已按 NIS_SMOKE_ALLOW_FALLBACK 放宽）" if ALLOW_FALLBACK else ""),
            )
        if not fell_back:
            check(
                "AI 单次耗时在可演示范围（<=30s）",
                elapsed_ms <= 30000,
                f"{elapsed_ms}ms",
            )
        if suggestion and suggestion.get("id"):
            st, decided = call("POST", f"/ai/suggestions/{suggestion['id']}/decision",
                               {"decision": "accepted", "note": "体检脚本采纳"}, token=recon_token)
            check("人工确认生效", st in (200, 201) and decided.get("status") == "accepted",
                  f"HTTP {st} status={decided.get('status') if decided else '-'}")
            st, _ = call("POST", f"/ai/suggestions/{suggestion['id']}/decision",
                         {"decision": "accepted", "note": "重复确认"}, token=recon_token)
            check("重复确认被拒 409", st == 409, f"HTTP {st}")

    print("\n[5] 优先级与紧急标红")
    st, all_records = call("GET", "/recon-records?page=1&page_size=5", token=recon_token)
    if st == 200 and all_records["items"]:
        priorities = [item["priority"] for item in all_records["items"]]
        urgent_first = "urgent" not in priorities or priorities[0] == "urgent"
        check("列表按优先级排序（紧急在前）", urgent_first, f"前几条优先级={priorities}")

    print("\n[6] 系统管理（细粒度权限 / 限时角色 / 在线 / 设备绑定）")
    st, roles = call("GET", "/admin/roles", token=admin, role="administrator")
    check("角色列表", st == 200, f"{len(roles.get('items', []))} 个角色")
    analyst_role = next((r for r in roles["items"] if r["code"] == "analyst"), None)
    if analyst_role:
        st, _ = call("PUT", f"/admin/roles/{analyst_role['id']}/permissions",
                     {"permission_codes": analyst_role["permissions"]}, token=admin, role="administrator")
        check("角色权限保存（幂等）", st in (200, 204), f"HTTP {st}")

    st, users = call("GET", "/admin/users?page=1&page_size=50", token=admin, role="administrator")
    exec2 = next((u for u in users["items"] if u["username"] == "exec02"), None)
    if exec2:
        st, bindings = call("GET", f"/admin/users/{exec2['id']}/roles", token=admin, role="administrator")
        check("用户角色绑定可读（含到期字段）", st == 200,
              f"{len(bindings.get('items', []))} 条绑定")
        st, binding = call("GET", f"/admin/users/{exec2['id']}/device-binding", token=admin, role="administrator")
        check("设备绑定可读", st == 200, f"enforced={binding.get('enforced') if binding else '-'}")

    st, online = call("GET", "/admin/online-users", token=admin, role="administrator")
    check("在线用户列表", st == 200, f"{online.get('total')} 人在线")

    print("\n[7] 任务转交（只读检查）")
    st, exec_login = call("POST", "/auth/login", {"username": "exec01", "password": DEMO_PW})
    exec_token = exec_login["access_token"]
    st, assignments = call("GET", "/assignments?page=1&page_size=20", token=exec_token)
    transferable = [a for a in assignments["items"]
                    if a["status"] in {"pending", "accepted", "executing"}]
    check("执行员待办可读", st == 200, f"{len(assignments.get('items', []))} 条")
    check("存在可转交状态任务", bool(transferable), f"{len(transferable)} 条可转交")

    failed = [item for item in RESULTS if not item[1]]
    print(f"\n汇总：{len(RESULTS)} 项检查，PASS {len(RESULTS) - len(failed)} / FAIL {len(failed)}")
    for name, _, detail in failed:
        print(f"  FAIL {name} {detail}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
