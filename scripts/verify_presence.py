"""验证在线状态查看与强制下线。"""

import json
import os
import sys
import uuid
from urllib import error, request

BASE = os.environ.get("NIS_BASE_URL", "http://127.0.0.1:8000/api/v1").rstrip("/")
ADMIN_PW = os.environ.get("NIS_ADMIN_PASSWORD", "")
DEMO_PW = os.environ.get("NIS_DEMO_PASSWORD", "")
RESULTS: list[tuple[str, bool, str]] = []


def rec(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def call(method, path, body=None, token=None, role=None):
    headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if role:
        headers["X-Role-Context"] = role
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw else None)


def main():
    status, payload = call("POST", "/auth/login", {"username": "admin", "password": ADMIN_PW})
    if status != 200:
        print("admin login failed", status, payload)
        return 2
    admin_token = payload["access_token"]
    roles = payload["user"]["roles"]
    admin_role = "administrator" if "administrator" in roles else roles[0]

    # 目标账号登录，产生一次会话
    status, target = call("POST", "/auth/login", {"username": "exec01", "password": DEMO_PW})
    rec("目标账号登录", status == 200, f"HTTP {status}")
    target_token = target["access_token"]
    target_id = target["user"]["id"]

    # 触发一次 /auth/me，写入在线状态
    status, _ = call("GET", "/auth/me", token=target_token)
    rec("目标账号可正常访问", status == 200, f"HTTP {status}")

    # 管理员查看在线列表
    status, online = call("GET", "/admin/online-users", token=admin_token, role=admin_role)
    rec("可查看在线用户列表", status == 200, f"HTTP {status}，{online.get('total')} 人在线")
    hit = next((i for i in online.get("items", []) if i["user_id"] == target_id), None)
    rec("目标账号在在线列表中且为在线", hit is not None and hit["online"] is True,
        f"last_seen={hit['last_seen_at'] if hit else None}")

    # 强制下线
    status, result = call("POST", f"/admin/users/{target_id}/force-logout",
                          token=admin_token, role=admin_role)
    rec("管理员执行强制下线", status == 200, f"HTTP {status} revoked_before={result.get('revoked_before') if result else ''}")

    status, body = call("GET", "/auth/me", token=target_token)
    rec("被下线账号旧令牌立即失效", status == 401, f"HTTP {status} {body.get('code') if body else ''}")

    status, body = call("GET", "/assignments?page=1&page_size=5", token=target_token)
    rec("被下线账号访问业务接口被拒", status == 401, f"HTTP {status}")

    # 重新登录后恢复
    status, again = call("POST", "/auth/login", {"username": "exec01", "password": DEMO_PW})
    rec("重新登录成功", status == 200, f"HTTP {status}")
    status, _ = call("GET", "/auth/me", token=again["access_token"])
    rec("新令牌可正常使用", status == 200, f"HTTP {status}")

    # 在线列表重新显示在线
    status, online = call("GET", "/admin/online-users", token=admin_token, role=admin_role)
    hit = next((i for i in online.get("items", []) if i["user_id"] == target_id), None)
    rec("重新登录后在线状态恢复正常", hit is not None and hit["online"] is True, "online=True")

    # 审计
    status, events = call("GET", "/audit-events?page=1&page_size=20&action=user.force_logout",
                          token=admin_token, role=admin_role)
    rec("强制下线写入审计", events.get("total", 0) >= 1, f"事件数 {events.get('total')}")

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n汇总：{len(RESULTS)} 条，PASS {len(RESULTS) - len(fails)} / FAIL {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
