#!/usr/bin/env python3
"""按 docs/data-model.md 第 12 节顺序执行全部 Schema 迁移。

用法：
    python scripts/migrate_all.py --dry-run
    python scripts/migrate_all.py
    python scripts/migrate_all.py --verify

环境变量（见 .env.example）：
    MYSQL_HOST / MYSQL_PORT            默认 127.0.0.1:3306
    NIS_MIGRATE_PASSWORD               迁移账号统一口令（本地/演示环境）
    <PREFIX>_DB_MIGRATE_USER/PASSWORD  需要区分时按服务覆盖
    NIS_ALEMBIC_URL                    只跑单个服务时的显式覆盖

迁移使用独立账号（决策 D-06）：``nis_<schema>_migrate``，不进运行时容器。
退出码：0 成功；1 迁移失败；2 参数或配置错误。
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICES_DIR = ROOT / "services"

#: 迁移顺序（数据模型第 12 节）：先 IAM，再 Audit，然后四段业务，最后 AI。
MIGRATION_ORDER = [
    ("iam-service", "IAM"),
    ("audit-service", "AUDIT"),
    ("recon-service", "RECON"),
    ("analysis-service", "ANALYSIS"),
    ("decision-service", "DECISION"),
    ("execution-service", "EXECUTION"),
    ("ai-service", "AI"),
]


def migrate_url(prefix: str) -> str:
    explicit = os.environ.get(f"{prefix}_DB_MIGRATE_URL", "").strip()
    if explicit:
        return explicit
    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    schema = f"nis_{prefix.lower()}"
    user = os.environ.get(f"{prefix}_DB_MIGRATE_USER", f"{schema}_migrate")
    password = os.environ.get(
        f"{prefix}_DB_MIGRATE_PASSWORD", os.environ.get("NIS_MIGRATE_PASSWORD", "")
    )
    if not password:
        raise SystemExit(
            "缺少迁移账号口令：请设置 NIS_MIGRATE_PASSWORD（或 <PREFIX>_DB_MIGRATE_PASSWORD）"
        )
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{schema}?charset=utf8mb4"


def run_service(service: str, prefix: str, dry_run: bool) -> None:
    service_dir = SERVICES_DIR / service
    url = migrate_url(prefix)
    env = os.environ.copy()
    env["NIS_ALEMBIC_URL"] = url
    env["PYTHONPATH"] = os.pathsep.join(
        [str(SERVICES_DIR / "_shared"), str(service_dir), env.get("PYTHONPATH", "")]
    ).strip(os.pathsep)
    # 口令只通过环境变量传给子进程，不打印。
    safe = url.split("@", 1)[1] if "@" in url else url
    print(f"[migrate] {service:<18} -> {safe}")
    if dry_run:
        return
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=service_dir,
        env=env,
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"迁移失败：{service}（退出码 {result.returncode}）")


def verify() -> int:
    """核对每个 Schema 的表数量，作为迁移成功的证据。"""

    sys.path.insert(0, str(SERVICES_DIR / "_shared"))
    from sqlalchemy import create_engine, inspect  # noqa: PLC0415

    failed = 0
    for service, prefix in MIGRATION_ORDER:
        url = migrate_url(prefix)
        schema = f"nis_{prefix.lower()}"
        try:
            engine = create_engine(url, future=True)
            with engine.connect() as conn:
                tables = inspect(conn).get_table_names()
        except Exception as exc:  # noqa: BLE001 - 证据脚本，打印原因即可
            print(f"[verify ] {schema:<18} 连接失败：{type(exc).__name__}")
            failed += 1
            continue
        print(f"[verify ] {schema:<18} {len(tables):>2} 张表：{', '.join(sorted(tables))}")
        engine.dispose()
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="按顺序执行全部服务迁移")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不连接数据库")
    parser.add_argument("--verify", action="store_true", help="迁移后核对各 Schema 的表")
    parser.add_argument(
        "--only", metavar="SERVICE", help="只迁移指定服务，例如 iam-service"
    )
    args = parser.parse_args()

    # 本地开发从仓库根 .env 补全未设置的键；真实环境变量优先。
    sys.path.insert(0, str(SERVICES_DIR / "_shared"))
    from nis_shared.config import load_env_file  # noqa: PLC0415

    load_env_file(ROOT / ".env")

    targets = MIGRATION_ORDER
    if args.only:
        targets = [item for item in MIGRATION_ORDER if item[0] == args.only]
        if not targets:
            print(f"未知服务：{args.only}", file=sys.stderr)
            return 2

    for service, prefix in targets:
        run_service(service, prefix, args.dry_run)

    if args.verify:
        if args.dry_run:
            print("[verify ] 跳过：dry-run 未连接数据库")
            return 0
        return verify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
