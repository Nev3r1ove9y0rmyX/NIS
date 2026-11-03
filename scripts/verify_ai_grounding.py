"""验证：AI 建议是否基于真实业务内容（而非凭空生成）。"""

import json
import os
import urllib.error
import urllib.request

BASE = "http://127.0.0.1/api/v1"
PW = "woshikedaxiaolanhua"
OP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def call(method, path, body=None, token=None, timeout=150):
    headers = {"Accept": "application/json"}
    data = None
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with OP.open(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"null")


def main() -> int:
    _, login = call("POST", "/auth/login", {"username": "recon01", "password": PW})
    tok = login["access_token"]
    _, records = call("GET", "/recon-records?page=1&page_size=5", token=tok)
    target = None
    for item in records["items"]:
        if "AI 直接分析验证" in (item.get("title") or ""):
            target = item
            break
    if target is None:
        target = records["items"][0]
    print("対象记录：", target["record_no"], "|", target["title"])
    print("记录正文：", (target.get("content") or "")[:80])

    st, sug = call("POST", "/ai/suggestions", {
        "stage": "recon", "business_object_type": "recon_record",
        "business_object_id": target["id"], "suggestion_type": "summary",
    }, token=tok)
    print("HTTP", st, "| model =", sug.get("model_name") if sug else None)
    content = (sug or {}).get("content") or {}
    text = json.dumps(content, ensure_ascii=False)
    print("建议：", text[:220])
    grounded = any(word in text for word in ("北侧", "08:00", "往返", "车辆"))
    print("是否引用记录内容：", "是" if grounded else "否")

    # 分析报告建议
    _, alogin = call("POST", "/auth/login", {"username": "analyst01", "password": PW})
    atok = alogin["access_token"]
    _, reports = call("GET", "/analysis-reports?page=1&page_size=5", token=atok)
    if reports.get("items"):
        rep = reports["items"][0]
        print("\n分析报告：", rep["report_no"], "|", rep["title"])
        st2, sug2 = call("POST", "/ai/suggestions", {
            "stage": "analysis", "business_object_type": "analysis_report",
            "business_object_id": rep["id"], "suggestion_type": "summary",
        }, token=atok)
        text2 = json.dumps((sug2 or {}).get("content") or {}, ensure_ascii=False)
        print("HTTP", st2, "| model =", sug2.get("model_name") if sug2 else None)
        print("建议：", text2[:220])
        findings = rep.get("key_findings") or ""
        key_words = [w for w in ("北侧", "南侧", "路段", "时段", "规律") if w in findings]
        grounded2 = any(w in text2 for w in key_words) if key_words else None
        print("报告关键发现：", findings[:60])
        print("是否引用报告内容：", {True: "是", False: "否", None: "无法判定"}[grounded2])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
