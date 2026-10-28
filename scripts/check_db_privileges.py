#!/usr/bin/env python3
"""核对数据库账号权限矩阵（决策 D-06）。

对每个 Schema 检查三件事：

1. 运行账号只拥有自己 Schema 的权限，没有其他 Schema 的任何权限；
2. 审计 Schema 的运行账号只有 ``SELECT``/``INSERT``，没有 ``UPDATE``/``DELETE``；
3. 运行账号没有 DDL 权限（建/改表被拒绝）。

需要 root 账号读取授权信息：``MYSQL_ROOT_PASSWORD``。
用法：``python scripts/check_db_privileges.py``
退出码：0 全部符合；1 存在不符合项；2 配置缺失。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "_shared"))

from nis_shared.config import load_env_file  # noqa: E402

SCHEMAS = ["nis_iam", "nis_recon", "nis_analysis", "nis_decision", "nis_execution", "nis_ai", "nis_audit"]

#: 审计账号刻意只给 SELECT/INSERT（数据模型 12.1）。
APPEND_ONLY_SCHEMA = "nis_audit"


def connect(user: str, password: str, database: str | None = None):  # noqa: ANN201
    import pymysql  # noqa: PLC0415

    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=user,
        password=password,
        database=database,
        autocommit=True,
        connect_timeout=5,
    )


def grants_of(conn, user: str) -> list[str]:  # noqa: ANN001
    with conn.cursor() as cur:
        cur.execute(f"SHOW GRANTS FOR '{user}'@'%'")
        return [row[0] for row in cur.fetchall()]


def check_grants(root, schema: str) -> list[str]:  # noqa: ANN001
    """返回不符合项列表，空表示通过。"""

    problems: list[str] = []
    app_user = f"{schema}_app"
    grants = grants_of(root, app_user)
    joined = " | ".join(grants)

    if f"`{schema}`.*" not in joined and f"{schema}.*" not in joined:
        problems.append(f"{app_user} 未获得 {schema} 的权限")
    for other in SCHEMAS:
        if other == schema:
            continue
        if f"`{other}`" in joined:
            problems.append(f"{app_user} 越权拥有 {other} 的权限")

    has = {verb: verb in joined.upper() for verb in ("SELECT", "INSERT", "UPDATE", "DELETE")}
    if not has["SELECT"] or not has["INSERT"]:
        problems.append(f"{app_user} 缺少必要的 SELECT/INSERT")

    if schema == APPEND_ONLY_SCHEMA:
        if has["UPDATE"] or has["DELETE"]:
            problems.append(f"{app_user} 不应拥有 UPDATE/DELETE（审计只追加）")
    elif not (has["UPDATE"] and has["DELETE"]):
        problems.append(f"{app_user} 缺少自己 Schema 的 UPDATE/DELETE")

    if "ALL PRIVILEGES" in joined.upper() or "CREATE" in joined.upper():
        problems.append(f"{app_user} 拥有 DDL/ALL PRIVILEGES，应只保留 DML")
    return problems


def check_functional() -> list[str]:
    """功能性验证：审计账号确实改不动、删不掉。"""

    problems: list[str] = []
    password = os.environ.get("AUDIT_DB_PASSWORD") or os.environ.get("NIS_DEV_APP_PASSWORD", "")
    if not password:
        return ["缺少 AUDIT_DB_PASSWORD，跳过功能性验证"]
    try:
        conn = connect("nis_audit_app", password, "nis_audit")
    except Exception as exc:  # noqa: BLE001
        return [f"审计账号无法连接：{type(exc).__name__}"]
    try:
        with conn.cursor() as cur:
            for sql in ("UPDATE audit_events SET result='failure'", "DELETE FROM audit_events"):
                try:
                    cur.execute(sql)
                except Exception as exc:  # noqa: BLE001 - 期望被拒绝
                    if type(exc).__name__ in {"OperationalError", "ProgrammingError"}:
                        continue
                    problems.append(f"意外的异常类型：{type(exc).__name__}")
                else:
                    problems.append(f"审计账号竟然可以执行：{sql.split()[0]}")
    finally:
        conn.close()
    return problems


def main() -> int:
    load_env_file(ROOT / ".env")
    root_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if not root_password:
        print("缺少 MYSQL_ROOT_PASSWORD：本脚本需要 root 读取授权信息。", file=sys.stderr)
        return 2

    root = connect("root", root_password)
    failures = 0
    try:
        for schema in SCHEMAS:
            problems = check_grants(root, schema)
            if problems:
                failures += 1
                for problem in problems:
                    print(f"[FAIL] {problem}")
            else:
                print(f"[ OK ] {schema}_app 权限符合 D-06 矩阵")
    finally:
        root.close()

    for problem in check_functional():
        print(f"[FAIL] {problem}")
        failures += 1

    print(f"结论：{'全部符合' if failures == 0 else f'{failures} 项不符合'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
