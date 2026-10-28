#!/usr/bin/env python3
"""写入 IAM 种子数据的命令行入口。

逻辑在 ``services/iam-service/app/seed.py``，本文件只负责环境变量、数据源和退出码。

用法：
    set NIS_ADMIN_PASSWORD=...      # 必需：admin 口令，不写入仓库
    set NIS_DEMO_PASSWORD=...       # 必需：演示账号统一初始口令（至少 8 位）
    python scripts/seed_data.py --dry-run
    python scripts/seed_data.py

退出码：0 成功；1 数据库错误；2 缺少必需环境变量。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "_shared"))
sys.path.insert(0, str(ROOT / "services" / "iam-service"))

from app.seed import seed  # noqa: E402
from nis_shared.config import load_env_file, load_settings  # noqa: E402
from nis_shared.db import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="写入 IAM 种子数据（组织/权限/角色/账号）")
    parser.add_argument("--dry-run", action="store_true", help="统计将新增的数量后回滚")
    args = parser.parse_args()

    # 本地开发从仓库根 .env 补全未设置的键；真实环境变量优先。
    load_env_file(ROOT / ".env")

    admin_password = os.environ.get("NIS_ADMIN_PASSWORD", "")
    demo_password = os.environ.get("NIS_DEMO_PASSWORD", "")
    if not admin_password or not demo_password:
        print(
            "缺少 NIS_ADMIN_PASSWORD 或 NIS_DEMO_PASSWORD：口令只能来自环境变量，不写入仓库。",
            file=sys.stderr,
        )
        return 2
    if len(demo_password) < 8:
        print("NIS_DEMO_PASSWORD 至少 8 位（演示账号同样要过弱口令检查）。", file=sys.stderr)
        return 2

    settings = load_settings("iam-service")
    database = Database(settings.db_url)
    if not database.ping():
        print("数据库不可达：请先执行 python scripts/migrate_all.py", file=sys.stderr)
        return 1

    try:
        counts = seed(
            database,
            admin_password=admin_password,
            demo_password=demo_password,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # noqa: BLE001 - 命令行工具，打印类型即可
        print(f"种子写入失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    suffix = "（dry-run，已回滚）" if args.dry_run else ""
    detail = "，".join(f"{name}+{value}" for name, value in counts.items())
    print(f"种子完成{suffix}：{detail}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
