"""在真实终端上验证 IP 绑定：源地址走外网口（192.168.146.1）。"""

import json
import urllib.error
import urllib.request

BASE = "http://192.168.146.10/api/v1"
ADMIN_PW = "woshikedaxiaolanhua"
DEMO_PW = "woshikedaxiaolanhua"
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, body=None, token=None, role=None):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if role:
        headers["X-Role-Context"] = role
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=10) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return exc.code, (json.loads(raw) if raw else None)


def login(user, pw):
    return call("POST", "/auth/login", {"username": user, "password": pw})


results = []


def rec(name, ok, detail=""):
    results.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


st, payload = login("admin", ADMIN_PW)
role = "administrator" if "administrator" in payload["user"]["roles"] else payload["user"]["roles"][0]
admin = payload["access_token"]
_, users = call("GET", "/admin/users?page_size=50", token=admin, role=role)
exec2 = next(u for u in users["items"] if u["username"] == "exec02")
uid = exec2["id"]

print("== 绑定到本终端地址 192.168.146.1 ==")
st, _ = call("PUT", f"/admin/users/{uid}/device-binding", {"allowed_ips": ["192.168.146.1"], "allowed_macs": []}, token=admin, role=role)
rec("设置绑定", st == 200, f"HTTP {st}")

st, body = login("exec02", DEMO_PW)
rec("绑定终端可以登录", st == 200, f"HTTP {st} {body.get('code') if body else ''}")

print("== 绑定到别的地址 ==")
call("PUT", f"/admin/users/{uid}/device-binding", {"allowed_ips": ["192.168.999.1"]}, token=admin, role=role)
st, body = login("exec02", DEMO_PW)
rec("非绑定终端被拒", st == 403, f"HTTP {st} {body.get('code') if body else ''}")

print("== 解除绑定 ==")
call("PUT", f"/admin/users/{uid}/device-binding", {"allowed_ips": [], "allowed_macs": []}, token=admin, role=role)
st, _ = login("exec02", DEMO_PW)
rec("解除后恢复登录", st == 200, f"HTTP {st}")

print(f"\n汇总：{len(results)} 条，PASS {sum(results)} / FAIL {len(results) - sum(results)}")
