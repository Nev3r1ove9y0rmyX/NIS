#!/usr/bin/env python3
"""为 NIS 演示环境创建固定组织、演示账号与一条完整的 OODA 演示数据。

只用标准库，避免给演示机器增加依赖。脚本通过公共 API（/api/v1）操作，不直接写数据库，
因此它同时可以当作第一条端到端业务链的冒烟测试。

用法：
    set NIS_ADMIN_PASSWORD=...        # 必需，管理账号密码，不写入仓库
    set NIS_DEMO_PASSWORD=...          # 必需，演示账号统一初始密码
    python scripts/seed_demo_data.py --dry-run
    python scripts/seed_demo_data.py
    python scripts/seed_demo_data.py --with-loop     # 额外跑完一条完整 OODA 链

可选环境变量：
    NIS_BASE_URL             默认 http://127.0.0.1:8000/api/v1（仅 http/https）
    NIS_ADMIN_USERNAME       默认 admin
    NIS_ALLOW_PRIVATE_TARGET 默认 1。脚本目标仅限运维配置的单一来源；
                             出于 SSRF 防护，回环/私网/保留地址需此开关显式允许
                             （本机与 DMZ 演示地址 10.1.1.20 属于此类）。设为 0
                             可强制只允许公网目标。跨源重定向一律拒绝。

退出码：0 成功；1 接口或校验失败；2 缺少必需环境变量。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import sys
import uuid
from typing import Any
from urllib import error, request
from urllib.parse import urlparse

BASE_URL = os.environ.get("NIS_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
# 本脚本只应指向运维人员自己配置的演示环境。默认地址与 DMZ 演示地址（10.1.1.20）
# 都属于回环/私网段，属于本工具的合法目标，因此默认允许；指向公网地址的部署
# 无需任何开关。该开关只影响目标地址分类，不改变"仅 http/https、固定单一源"。
ALLOW_PRIVATE_TARGET = os.environ.get("NIS_ALLOW_PRIVATE_TARGET", "1") not in ("0", "false", "no")
ADMIN_USERNAME = os.environ.get("NIS_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("NIS_ADMIN_PASSWORD", "")
DEMO_PASSWORD = os.environ.get("NIS_DEMO_PASSWORD", "")

ORGANIZATIONS: list[dict[str, str]] = [
    {"code": "ORG-CMD", "name": "联合指挥所", "unit_type": "command", "parent_code": ""},
    {"code": "ORG-REC", "name": "侦察分队", "unit_type": "recon_team", "parent_code": "ORG-CMD"},
    {"code": "ORG-ANA", "name": "分析组", "unit_type": "analysis_team", "parent_code": "ORG-CMD"},
    {"code": "ORG-DEC", "name": "决策组", "unit_type": "staff", "parent_code": "ORG-CMD"},
    {"code": "ORG-EXE", "name": "执行分队", "unit_type": "execution_team", "parent_code": "ORG-CMD"},
]

# username, display_name, organization_code, roles
DEMO_USERS: list[dict[str, Any]] = [
    {"username": "recon01", "display_name": "侦察员甲", "organization_code": "ORG-REC", "roles": ["reconnaissance"]},
    {"username": "recon02", "display_name": "侦察员乙", "organization_code": "ORG-REC", "roles": ["reconnaissance"]},
    {"username": "analyst01", "display_name": "分析员甲", "organization_code": "ORG-ANA", "roles": ["analyst"]},
    {"username": "analyst02", "display_name": "分析员乙", "organization_code": "ORG-ANA", "roles": ["analyst"]},
    {"username": "dmaker01", "display_name": "决策员甲", "organization_code": "ORG-DEC", "roles": ["decision_maker"]},
    {"username": "exec01", "display_name": "执行员甲", "organization_code": "ORG-EXE", "roles": ["executor"]},
    {"username": "exec02", "display_name": "执行员乙", "organization_code": "ORG-EXE", "roles": ["executor"]},
]

DEMO_RECON = {
    "title": "演示用：目标区域活动规律观察",
    "source_type": "osint",
    "source_ref": "演示环境内部素材，已脱敏",
    "content": (
        "在课程授权的演示环境中，观察到目标区域每日固定时段出现人员与车辆往返，"
        "路线相对固定，伴随无线电通联活动。以上内容为演示数据，不对应任何真实目标。"
    ),
    "credibility": "medium",
    "priority": "urgent",
}


class ApiError(RuntimeError):
    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload
        message = ""
        if isinstance(payload, dict):
            message = f"{payload.get('code')}: {payload.get('message')}"
        super().__init__(f"HTTP {status} {message}".strip())


def _key() -> str:
    return str(uuid.uuid4())


def _validate_target(url: str) -> str:
    """请求前校验目标：仅 http/https，且必须是指定的单一来源。

    本脚本不从任何网络输入获取 URL，目标只来自运维环境变量 NIS_BASE_URL；
    即便如此仍做三重防护，防止配置被篡改后变成 SSRF 跳板：
    1. 仅放行 http/https（阻断 file:// 等协议与重定向到其它协议）；
    2. 解析 host 并分类：回环/私网/保留地址必须显式允许（演示环境默认允许）；
    3. 校验后的 url 原样返回，urlopen 只接收本校验过的值，不跟随跨源重定向。
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit(f"拒绝请求：仅允许 http/https，实际为 {parsed.scheme!r}")
    if parsed.username or parsed.password:
        raise SystemExit("拒绝请求：目标 URL 不允许携带内联凭据")
    host = parsed.hostname
    if not host:
        raise SystemExit(f"拒绝请求：目标缺少主机名 {url!r}")

    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        if host.lower() == "localhost" and not ALLOW_PRIVATE_TARGET:
            raise SystemExit(
                "拒绝请求：localhost 属于回环地址；如确需指向本机演示环境，"
                "设置 NIS_ALLOW_PRIVATE_TARGET=1"
            )
    else:
        blocked = (
            ("回环", addr.is_loopback),
            ("私网", addr.is_private),
            ("链路本地", addr.is_link_local),
            ("保留", addr.is_reserved),
            ("组播", addr.is_multicast),
        )
        blocked_kind = next((kind for kind, hit in blocked if hit), "")
        if blocked_kind and not ALLOW_PRIVATE_TARGET:
            raise SystemExit(
                f"拒绝请求：目标 {host} 属于{blocked_kind}地址；"
                "如确需指向内网/本机演示环境，设置 NIS_ALLOW_PRIVATE_TARGET=1"
            )
    return url


def _parse(raw: bytes, content_type: str) -> Any:
    if not raw:
        return None
    text = raw.decode("utf-8", errors="replace")
    if "json" in content_type or text.lstrip().startswith(("{", "[")):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return text


class _SameOriginRedirectHandler(request.HTTPRedirectHandler):
    """禁止跨源重定向：3xx 只允许指向同一 host:port，其余视为错误。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        old, new = urlparse(req.full_url), urlparse(newurl)
        same = (old.scheme in ("http", "https") and old.scheme == new.scheme
                and old.hostname == new.hostname and old.port == new.port)
        if not same:
            raise error.URLError(f"拒绝跨源重定向 {req.full_url} -> {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = request.build_opener(_SameOriginRedirectHandler)


class Client:
    """一个带身份的 API 客户端；每个角色使用独立实例，避免串号。"""

    def __init__(self, base_url: str = BASE_URL) -> None:
        # 固定单一目标源：所有请求只能发往该 host（见 _validate_target）。
        self.base_url = _validate_target(base_url)
        self.origin = (urlparse(base_url).scheme, urlparse(base_url).hostname,
                       urlparse(base_url).port)
        self.token = ""
        self.username = ""
        self.role_context: str | None = None

    def send(self, method: str, path: str, body: dict[str, Any] | None = None,
             idempotency_key: str | None = None,
             expect: tuple[int, ...] = (200, 201, 204)) -> Any:
        url = _validate_target(f"{self.base_url}{path}")
        if (urlparse(url).scheme, urlparse(url).hostname, urlparse(url).port) != self.origin:
            raise SystemExit(f"拒绝请求：目标偏离固定来源 {url!r}")
        data = None
        headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        if self.role_context:
            # 决策 D-03：多角色用户必须声明本次操作使用的角色。
            headers["X-Role-Context"] = self.role_context
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        req = request.Request(url, data=data, headers=headers, method=method)
        try:
            with _OPENER.open(req, timeout=30) as response:
                raw = response.read()
                status = response.status
                content_type = response.headers.get("Content-Type", "")
        except error.HTTPError as exc:
            raise ApiError(exc.code, _parse(exc.read(), exc.headers.get("Content-Type", ""))) from exc
        except error.URLError as exc:
            raise SystemExit(
                f"无法连接 {url}：{exc.reason}\n请确认 Gateway 已启动，或设置 NIS_BASE_URL。"
            ) from exc
        if status not in expect:
            raise ApiError(status, _parse(raw, content_type))
        return _parse(raw, content_type) if raw else None

    def login(self, username: str, password: str) -> dict[str, Any]:
        payload = self.send("POST", "/auth/login", {"username": username, "password": password})
        self.token = payload["access_token"]
        self.username = username
        roles = [str(role) for role in payload["user"].get("roles", [])]
        # 决策 D-03：单角色可省略，多角色必须显式声明；管理账号优先用 administrator。
        if len(roles) > 1:
            self.role_context = "administrator" if "administrator" in roles else roles[0]
        else:
            self.role_context = None
        return payload["user"]


def client_for(username: str, password: str) -> Client:
    client = Client()
    user = client.login(username, password)
    print(f"  已登录 {username}（{user['display_name']}，{', '.join(user['roles'])}）")
    return client


def ensure_organizations(admin: Client, dry_run: bool) -> dict[str, str]:
    existing = {item["code"]: item["id"] for item in admin.send("GET", "/organizations")["items"]}
    result: dict[str, str] = {}
    for spec in ORGANIZATIONS:
        code = spec["code"]
        if code in existing:
            result[code] = existing[code]
            print(f"  组织已存在 {code} -> {existing[code]}")
            continue
        if dry_run:
            print(f"  将创建组织 {code} {spec['name']}")
            continue
        body: dict[str, Any] = {
            "code": code,
            "name": spec["name"],
            "unit_type": spec["unit_type"],
        }
        parent_code = spec["parent_code"]
        if parent_code:
            parent_id = result.get(parent_code) or existing.get(parent_code)
            if not parent_id:
                raise SystemExit(f"父组织 {parent_code} 尚未创建，无法创建 {code}")
            body["parent_id"] = parent_id
        created = admin.send("POST", "/admin/organizations", body, _key())
        result[code] = created["id"]
        print(f"  已创建组织 {code} -> {created['id']}")
    return result


def check_roles(admin: Client) -> None:
    roles = {role["code"]: role for role in admin.send("GET", "/admin/roles")["items"]}
    required = ["reconnaissance", "analyst", "decision_maker", "executor"]
    missing = [code for code in required if code not in roles]
    if missing:
        raise SystemExit(
            "缺少标准角色：" + "、".join(missing)
            + "\n请先执行 IAM 服务的迁移与权限种子，再运行本脚本。"
        )
    for code in required:
        if not roles[code].get("permissions"):
            print(f"  [警告] 角色 {code} 没有任何权限，请检查角色权限种子")
    print("  标准角色齐全：" + "、".join(required))


def ensure_users(admin: Client, orgs: dict[str, str], password: str,
                 dry_run: bool) -> dict[str, str]:
    existing = {item["username"]: item for item in admin.send("GET", "/admin/users?page=1&page_size=100")["items"]}
    result: dict[str, str] = {}
    for spec in DEMO_USERS:
        username = spec["username"]
        if username in existing:
            result[username] = existing[username]["id"]
            print(f"  账号已存在 {username} -> {existing[username]['id']}")
            continue
        if dry_run:
            print(f"  将创建账号 {username}（{spec['display_name']}）")
            continue
        body = {
            "username": username,
            "password": password,
            "display_name": spec["display_name"],
            "organization_id": orgs[spec["organization_code"]],
            "role_codes": spec["roles"],
        }
        created = admin.send("POST", "/admin/users", body, _key())
        result[username] = created["id"]
        print(f"  已创建账号 {username} -> {created['id']}")
    return result


def run_full_loop(users: dict[str, str]) -> dict[str, str]:
    """以四个不同账号按 OODA 顺序跑通一次真实业务链。"""
    trace: dict[str, str] = {}

    recon_client = client_for("recon01", DEMO_PASSWORD)
    print("  [1/5] 侦察员创建并提交侦察记录")
    recon = recon_client.send("POST", "/recon-records", {**DEMO_RECON, "evidence": []}, _key())
    trace["recon_record_id"] = recon["id"]
    recon = recon_client.send(
        "POST",
        f"/recon-records/{recon['id']}/submit",
        {"expected_version": recon["version"], "analyst_ids": [users["analyst01"]]},
        _key(),
    )
    trace["recon_status"] = recon["status"]

    analyst_client = client_for("analyst01", DEMO_PASSWORD)
    print("  [2/5] 分析员创建并提交分析报告")
    report = analyst_client.send(
        "POST",
        "/analysis-reports",
        {
            "title": "演示用：区域活动规律分析",
            "recon_record_ids": [trace["recon_record_id"]],
            "key_findings": "活动时间与路线高度规律，具备固定保障节点特征。",
            "relations": "人员往返与车辆调度在同一时段出现，两者存在时间耦合。",
            "risk_level": "medium",
            "recommended_actions": "建议在固定时段前完成观察点部署，并保留影像证据。",
            "priority": "urgent",
        },
        _key(),
    )
    trace["analysis_report_id"] = report["id"]
    report = analyst_client.send(
        "POST",
        f"/analysis-reports/{report['id']}/submit",
        {
            "expected_version": report["version"],
            "decision_maker_ids": [users["dmaker01"]],
            "ai_content_confirmed": True,
        },
        _key(),
    )
    trace["report_status"] = report["status"]

    decision_client = client_for("dmaker01", DEMO_PASSWORD)
    print("  [3/5] 决策员创建并下达指令")
    command = decision_client.send(
        "POST",
        "/commands",
        {
            "title": "演示用：固定时段观察任务",
            "objective": "在固定时段获取目标区域活动证据",
            "content": "提前 30 分钟到达观察点，按约定频段通联，只做观察与记录，不主动接触。",
            "priority": "urgent",
            "source_report_id": trace["analysis_report_id"],
        },
        _key(),
    )
    trace["command_id"] = command["id"]
    command = decision_client.send(
        "POST",
        f"/commands/{command['id']}/issue",
        {
            "expected_version": command["version"],
            "executor_ids": [users["exec01"]],
            "conflict_acknowledged": True,
        },
        _key(),
    )
    trace["command_status"] = command["status"]

    exec_client = client_for("exec01", DEMO_PASSWORD)
    print("  [4/5] 执行员接收、开始并提交结果")
    assignments = exec_client.send("GET", "/assignments?page_size=50")["items"]
    target = next((item for item in assignments if item.get("command_id") == trace["command_id"]), None)
    if target is None:
        raise SystemExit("未找到新下达指令对应的执行分配，请检查 Execution 服务")
    trace["assignment_id"] = target["id"]
    for action in ("accept", "start"):
        target = exec_client.send(
            "POST",
            f"/assignments/{target['id']}/{action}",
            {"expected_version": target["version"]},
        )
    target = exec_client.send(
        "POST",
        f"/assignments/{target['id']}/complete",
        {
            "expected_version": target["version"],
            "outcome": "success",
            "summary": "按计划完成观察，取得 3 段连续记录。",
            "detail": "观察期间未发生异常接触，证据已按要求存放在受控目录。",
        },
        _key(),
    )
    trace["assignment_status"] = target["status"]

    print("  [5/5] 决策员回看执行结果")
    status_view = decision_client.send("GET", f"/commands/{trace['command_id']}/status")
    trace["command_aggregate_status"] = status_view["status"]
    return trace


def main() -> int:
    parser = argparse.ArgumentParser(description="创建 NIS 演示组织、账号与演示数据")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要执行的动作")
    parser.add_argument("--with-loop", action="store_true", help="额外跑通一条完整 OODA 业务链")
    args = parser.parse_args()

    if not ADMIN_PASSWORD or not DEMO_PASSWORD:
        print(
            "缺少环境变量：请设置 NIS_ADMIN_PASSWORD 与 NIS_DEMO_PASSWORD。\n"
            "演示密码只放在本地 .env 或当前 shell，不得写入仓库。",
            file=sys.stderr,
        )
        return 2

    print(f"目标环境：{BASE_URL}")
    orgs: dict[str, str] = {spec["code"]: "<pending>" for spec in ORGANIZATIONS}
    users: dict[str, str] = {spec["username"]: "<pending>" for spec in DEMO_USERS}
    trace: dict[str, str] = {}

    if args.dry_run:
        print("步骤 1：[dry-run] 跳过管理账号登录")
        print("步骤 2：[dry-run] 将检查四类标准角色")
        print("步骤 3：[dry-run] 将创建 5 个组织单元")
        print("步骤 4：[dry-run] 将创建 7 个演示账号")
    else:
        print("步骤 1：以管理账号登录")
        admin = client_for(ADMIN_USERNAME, ADMIN_PASSWORD)
        print("步骤 2：检查标准角色")
        check_roles(admin)
        print("步骤 3：创建组织结构")
        orgs = ensure_organizations(admin, args.dry_run)
        print("步骤 4：创建演示账号")
        users = ensure_users(admin, orgs, DEMO_PASSWORD, args.dry_run)
        if args.with_loop:
            print("步骤 5：跑通完整 OODA 业务链")
            trace = run_full_loop(users)

    print("\n汇总")
    print(f"  组织：{len(orgs)} 个")
    for code, identifier in orgs.items():
        print(f"    {code}: {identifier}")
    print(f"  账号：{len(users)} 个")
    for username, identifier in users.items():
        print(f"    {username}: {identifier}")
    if trace:
        print("  业务链：")
        for key, value in trace.items():
            print(f"    {key}: {value}")
    print("\n提示：以上 ID 可直接用于演示前的数据核对；密码只保存在本地。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
