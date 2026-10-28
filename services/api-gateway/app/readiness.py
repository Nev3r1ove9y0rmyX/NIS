"""Gateway 就绪探针。

Gateway 不拥有数据库（docs/data-ownership.md 第 1 节），它的就绪状态取决于关键下游是否
可达。探针并发请求各服务的 ``/health/live``，结果只用于报告，不改动业务状态
（docs/soa-deployment.md 第 6 节）。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

PROBE_TIMEOUT_SECONDS = 1.0


def _probe_one(name: str, base_url: str, timeout: float) -> tuple[str, str]:
    try:
        response = httpx.get(f"{base_url.rstrip('/')}/health/live", timeout=timeout)
    except httpx.HTTPError:
        return name, "unreachable"
    if response.status_code == 200:
        return name, "ok"
    return name, f"http_{response.status_code}"


def probe_downstreams(
    downstream: dict[str, str], timeout: float = PROBE_TIMEOUT_SECONDS
) -> dict[str, str]:
    """并发探测下游服务；返回 ``{服务名: 状态}``，不抛异常。"""

    if not downstream:
        return {}
    with ThreadPoolExecutor(max_workers=len(downstream)) as pool:
        results = pool.map(
            lambda item: _probe_one(item[0], item[1], timeout), downstream.items()
        )
        return dict(results)
