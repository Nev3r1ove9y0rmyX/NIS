#!/usr/bin/env python3
"""本地 SQLite 全栈开发启动器（成员 C 添加，用于前端联调）。

为什么需要它：正式环境按 [部署说明](../deploy/README.md) 走 Docker Compose + MySQL，
但前端联调（C-03 至 C-09）在 Windows 本机需要一条「不开 Docker 也能接真实接口」的路径。
本脚本只做三件事：建表、写种子、起 8 个进程，**不修改任何服务代码**，也不改变正式运行方式。

用法：

    set NIS_ADMIN_PASSWORD=...      # 必需：admin 口令
    set NIS_DEMO_PASSWORD=...       # 必需：演示账号口令（>=8 位）
    python scripts/dev_stack.py init       # 建表 + IAM 种子
    python scripts/dev_stack.py run        # 启动 8 个服务，Ctrl+C 全部停止
    python scripts/dev_stack.py status     # 逐个健康检查
    python scripts/dev_stack.py stop       # 按 .localdata/pids.json 结束残留进程

数据落在仓库内 ``.localdata/``（已在 .gitignore 中）：每个服务一个 SQLite 文件，
证据目录 ``.localdata/evidence``，日志 ``.localdata/logs/<service>.log``。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "services"
SHARED_DIR = SERVICES_DIR / "_shared"
DATA_DIR = ROOT / ".localdata"
LOG_DIR = DATA_DIR / "logs"
PIDS_FILE = DATA_DIR / "pids.json"

#: 启动顺序：先身份与审计，再四段业务，最后网关。
SERVICES: list[tuple[str, str, int]] = [
    ("iam-service", "IAM", 8001),
    ("audit-service", "AUDIT", 8007),
    ("recon-service", "RECON", 8002),
    ("analysis-service", "ANALYSIS", 8003),
    ("decision-service", "DECISION", 8004),
    ("execution-service", "EXECUTION", 8005),
    ("ai-service", "AI", 8006),
    ("api-gateway", "GATEWAY", 8000),
]

SERVICE_URL_ENV = {
    "iam-service": "IAM_SERVICE_URL",
    "recon-service": "RECON_SERVICE_URL",
    "analysis-service": "ANALYSIS_SERVICE_URL",
    "decision-service": "DECISION_SERVICE_URL",
    "execution-service": "EXECUTION_SERVICE_URL",
    "ai-service": "AI_SERVICE_URL",
    "audit-service": "AUDIT_SERVICE_URL",
}


def python_exe() -> str:
    """优先使用仓库 .venv，其次当前解释器。"""

    candidate = ROOT / ".venv" / "Scripts" / "python.exe"
    if candidate.is_file():
        return str(candidate)
    return sys.executable


def sqlite_url(prefix: str) -> str:
    path = (DATA_DIR / f"{prefix.lower()}.db").as_posix()
    return f"sqlite+pysqlite:///{path}"


def service_env(prefix: str) -> dict[str, str]:
    """单个服务的环境变量：数据源、下游地址、证据目录。"""

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env.setdefault("APP_ENV", "development")
    env.setdefault("APP_LOG_LEVEL", "INFO")
    env.setdefault("EVIDENCE_ROOT", str(DATA_DIR / "evidence"))
    if prefix != "GATEWAY":
        env[f"{prefix}_DB_URL"] = sqlite_url(prefix)
    port_of = {service: port for service, _, port in SERVICES}
    for name, env_key in SERVICE_URL_ENV.items():
        env.setdefault(env_key, f"http://127.0.0.1:{port_of[name]}")
    return env


def active_port(service: str) -> int:
    """服务实际监听端口；Gateway 允许用 ``GATEWAY_PORT`` 覆盖（本机 8000 被占用时）。"""

    for name, _, port in SERVICES:
        if name == service:
            override = os.environ.get("GATEWAY_PORT", "").strip()
            if service == "api-gateway" and override.isdigit():
                return int(override)
            return port
    raise KeyError(service)



def init_database() -> int:
    """逐服务建表。

    每个服务都在独立子进程里导入，避免 7 个同名 ``app`` 包互相覆盖
    （与 ``tests/conftest.py`` 处理的是同一个问题）。
    """

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "evidence").mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    failed = 0
    for service, prefix, _ in SERVICES:
        if service == "api-gateway":
            print(f"  {service:<18} -> 跳过（Gateway 不拥有 Schema）")
            continue
        snippet = (
            "import sys\n"
            f"sys.path.insert(0, {str(SHARED_DIR)!r})\n"
            f"sys.path.insert(0, {str(SERVICES_DIR / service)!r})\n"
            "from nis_shared.config import load_settings\n"
            "from nis_shared.db import Database\n"
            "import app.models  # noqa: F401  注册本服务的数据表\n"
            f"settings = load_settings({service!r})\n"
            "database = Database(settings.db_url)\n"
            "database.create_all()\n"
            f"print('  {service:<18} -> ' + settings.db_url)\n"
        )
        result = subprocess.run(
            [python_exe(), "-c", snippet],
            cwd=SERVICES_DIR / service,
            env=service_env(prefix),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode != 0:
            failed += 1
            print(f"  {service:<18} -> 失败：{(result.stderr or '').strip()[-400:]}")
        else:
            print((result.stdout or "").rstrip())

    if failed:
        print(f"建表失败的服务数：{failed}", file=sys.stderr)
        return 1

    seed = subprocess.run(
        [python_exe(), str(ROOT / "scripts" / "seed_data.py")],
        cwd=ROOT,
        env=service_env("IAM"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    print((seed.stdout or "").strip())
    if seed.returncode != 0:
        print(f"种子失败：{(seed.stderr or '').strip()[-600:]}", file=sys.stderr)
        return seed.returncode
    return 0


def start_all() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    pids: dict[str, int] = {}
    processes: list[subprocess.Popen] = []
    base_env = os.environ.copy()
    base_env["PYTHONUTF8"] = "1"

    for service, prefix, declared_port in SERVICES:
        port = active_port(service)
        env = service_env(prefix)
        env["PYTHONPATH"] = os.pathsep.join([str(SERVICES_DIR / service), str(SHARED_DIR)])
        log_path = LOG_DIR / f"{service}.log"
        handle = open(log_path, "w", encoding="utf-8")  # noqa: SIM115 - 交给子进程持有
        process = subprocess.Popen(
            [
                python_exe(),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "info",
            ],
            cwd=SERVICES_DIR / service,
            env=env,
            stdout=handle,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
        processes.append(process)
        pids[service] = process.pid
        print(f"[start ] {service:<18} pid={process.pid:<7} port={port} log={log_path}")

    PIDS_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")
    print(f"[info  ] pid 清单：{PIDS_FILE}")

    deadline = time.time() + 60
    import urllib.request as _url  # noqa: PLC0415

    pending = {service: active_port(service) for service, _, _ in SERVICES}
    while pending and time.time() < deadline:
        for service in list(pending):
            port = pending[service]
            try:
                with _url.urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=2) as resp:
                    if resp.status == 200:
                        print(f"[ready ] {service:<18} port={port}")
                        pending.pop(service)
            except (urllib.error.URLError, OSError):
                pass
        if pending:
            time.sleep(1.5)

    if pending:
        print(f"[warn  ] 未就绪：{', '.join(pending)}（看 .localdata/logs/）")
    else:
        print(
            f"[ready ] 8 个服务全部就绪：前端可指向 http://127.0.0.1:{active_port('api-gateway')}/api/v1"
        )

    running = {service: process for service, process in zip([s for s, _, _ in SERVICES], processes, strict=False)}
    try:
        while True:
            time.sleep(1)
            for service, process in list(running.items()):
                if process.poll() is not None:
                    print(f"[exit  ] {service} 已退出，code={process.returncode}")
                    running.pop(service)
            if not running:
                print("[stop  ] 所有服务已退出")
                return 0
    except KeyboardInterrupt:
        print("[stop  ] 收到中断，结束全部服务")
        for process in running.values():
            process.terminate()
        for process in running.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        return 0


def stop_all() -> int:
    if not PIDS_FILE.is_file():
        print("没有 pid 清单，无需停止")
        return 0
    pids = json.loads(PIDS_FILE.read_text(encoding="utf-8"))
    for service, pid in pids.items():
        result = subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        print(f"[kill  ] {service:<18} pid={pid} {result.returncode}")
    PIDS_FILE.unlink(missing_ok=True)
    return 0


def status() -> int:
    healthy = 0
    for service, _, _ in SERVICES:
        port = active_port(service)
        url = f"http://127.0.0.1:{port}/health/ready"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                body = resp.read().decode("utf-8")
                print(f"[ok    ] {service:<18} {port} {body[:120]}")
                healthy += 1
        except Exception as exc:  # noqa: BLE001 - 证据脚本，打印原因即可
            print(f"[down  ] {service:<18} {port} {type(exc).__name__}")
    return 0 if healthy == len(SERVICES) else 1


def load_local_env() -> None:
    """读取仓库根 ``.env``（不覆盖已存在的环境变量），与各服务行为保持一致。"""

    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main() -> int:
    parser = argparse.ArgumentParser(description="本地 SQLite 全栈开发启动器")
    parser.add_argument("action", choices=["init", "run", "status", "stop"])
    args = parser.parse_args()
    load_local_env()
    if args.action == "init":
        return init_database()
    if args.action == "run":
        return start_all()
    if args.action == "status":
        return status()
    return stop_all()


if __name__ == "__main__":
    raise SystemExit(main())
