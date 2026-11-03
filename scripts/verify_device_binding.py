"""验证账号与终端 IP/MAC 绑定。"""

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


def call(method, path, body=None, token=None, role=None, mac=None):
    headers = {"Accept": "application/json", "X-Request-ID": str(uuid.uuid4())}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if role:
        headers["X-Role-Context"] = role
    if mac:
        headers["X-Device-MAC"] = mac
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


def login(username, password, mac=None):
    return call("POST", "/auth/login", {"username": username, "password": password}, mac=mac)


def main():
    status, payload = login("admin", ADMIN_PW)
    if status != 200:
        print("admin login failed", status, payload)
        return 2
    token = payload["access_token"]
    roles = payload["user"]["roles"]
    role = "administrator" if "administrator" in roles else roles[0]

    _, users = call("GET", "/admin/users?page=1&page_size=50", token=token, role=role)
    target = next(u for u in users["items"] if u["username"] == "exec02")
    uid = target["id"]

    # 1. 绑定一个不存在的 IP -> 登录被拒
    status, binding = call("PUT", f"/admin/users/{uid}/device-binding",
                           {"allowed_ips": ["10.99.99.99"], "allowed_macs": []}, token=token, role=role)
    rec("设置 IP 绑定", status == 200 and binding["enforced"] is True, f"HTTP {status}")
    status, body = login("exec02", DEMO_PW)
    rec("非绑定终端登录被拒", status == 403, f"HTTP {status} {body.get('code') if body else ''}")

    # 2. 绑定当前地址 127.0.0.1 -> 登录成功
    call("PUT", f"/admin/users/{uid}/device-binding",
         {"allowed_ips": ["127.0.0.1"], "allowed_macs": []}, token=token, role=role)
    status, body = login("exec02", DEMO_PW)
    rec("绑定终端登录成功", status == 200, f"HTTP {status}")

    # 3. 再加 MAC 绑定，缺 MAC 头 -> 拒绝
    call("PUT", f"/admin/users/{uid}/device-binding",
         {"allowed_ips": ["127.0.0.1"], "allowed_macs": ["AA:BB:CC:DD:EE:FF"]}, token=token, role=role)
    status, body = login("exec02", DEMO_PW)
    rec("缺少 MAC 时被拒", status == 403, f"HTTP {status} {body.get('code') if body else ''}")
    status, body = login("exec02", DEMO_PW, mac="aa:bb:cc:dd:ee:01")
    rec("MAC 不匹配被拒", status == 403, f"HTTP {status}")
    status, body = login("exec02", DEMO_PW, mac="aa:bb:cc:dd:ee:ff")
    rec("MAC 匹配允许登录", status == 200, f"HTTP {status}")

    # 4. 非法 IP 格式
    status, body = call("PUT", f"/admin/users/{uid}/device-binding",
                        {"allowed_ips": ["abc"], "allowed_macs": []}, token=token, role=role)
    rec("非法 IP 被拒绝", status == 400, f"HTTP {status} {body.get('code') if body else ''}")

    # 5. 解除绑定后恢复
    status, binding = call("PUT", f"/admin/users/{uid}/device-binding",
                           {"allowed_ips": [], "allowed_macs": []}, token=token, role=role)
    rec("解除绑定", status == 200 and binding["enforced"] is False, f"HTTP {status}")
    status, _ = login("exec02", DEMO_PW)
    rec("解除后任意终端可登录", status == 200, f"HTTP {status}")

    # 6. 绑定变更写审计
    _, events = call("GET", "/audit-events?page=1&page_size=50&action=user.device_binding.update",
                     token=token, role=role)
    rec("绑定变更记入审计", events["total"] >= 1, f"事件数 {events.get('total')}")

    fails = [r for r in RESULTS if not r[1]]
    print(f"\n汇总：{len(RESULTS)} 条，PASS {len(RESULTS) - len(fails)} / FAIL {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
