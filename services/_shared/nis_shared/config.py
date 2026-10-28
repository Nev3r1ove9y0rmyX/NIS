"""服务配置。

约定（见 .env.example 与 docs/soa-deployment.md 第 5 节）：

- 所有配置从环境变量读取，仓库里只有占位值；
- 每个服务只读取自己的数据库账号变量，不共用一个万能账号；
- 本地开发可以从仓库根目录的 ``.env`` 补全未设置的键（已设置的环境变量优先）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

#: 服务名 → 该服务数据库环境变量前缀
SERVICE_DB_PREFIX: dict[str, str] = {
    "api-gateway": "GATEWAY",
    "iam-service": "IAM",
    "recon-service": "RECON",
    "analysis-service": "ANALYSIS",
    "decision-service": "DECISION",
    "execution-service": "EXECUTION",
    "ai-service": "AI",
    "audit-service": "AUDIT",
}

#: 服务名 → 内部端口
SERVICE_PORT: dict[str, int] = {
    "api-gateway": 8000,
    "iam-service": 8001,
    "recon-service": 8002,
    "analysis-service": 8003,
    "decision-service": 8004,
    "execution-service": 8005,
    "ai-service": 8006,
    "audit-service": 8007,
}

#: 服务名 → 内部地址环境变量名
SERVICE_URL_ENV: dict[str, str] = {
    "iam-service": "IAM_SERVICE_URL",
    "recon-service": "RECON_SERVICE_URL",
    "analysis-service": "ANALYSIS_SERVICE_URL",
    "decision-service": "DECISION_SERVICE_URL",
    "execution-service": "EXECUTION_SERVICE_URL",
    "ai-service": "AI_SERVICE_URL",
    "audit-service": "AUDIT_SERVICE_URL",
}


def load_env_file(path: str | os.PathLike[str] | None = None) -> None:
    """把 ``.env`` 里的键补进环境变量；已存在的环境变量不覆盖。

    不引入 python-dotenv：格式只需要 ``KEY=VALUE`` 与 ``#`` 注释。
    """

    if path is None:
        path = Path(__file__).resolve().parents[3] / ".env"
    p = Path(path)
    if not p.is_file():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass(frozen=True)
class ServiceSettings:
    """单个服务的运行配置。"""

    service: str
    app_env: str = "development"
    log_level: str = "INFO"
    db_url: str = ""
    db_check_timeout_seconds: float = 3.0
    downstream: dict[str, str] = field(default_factory=dict)

    @property
    def is_dev(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "local", "test"}

    @property
    def port(self) -> int:
        return SERVICE_PORT[self.service]


def build_db_url(service: str) -> str:
    """按 ``MYSQL_HOST/PORT`` 加本服务账号拼出 SQLAlchemy DSN。"""

    if service == "api-gateway":
        # Gateway 不拥有 Schema（docs/data-ownership.md 第 1 节）。
        return ""

    prefix = SERVICE_DB_PREFIX[service]
    explicit = os.environ.get(f"{prefix}_DB_URL", "").strip()
    if explicit:
        return explicit

    host = os.environ.get("MYSQL_HOST", "127.0.0.1")
    port = os.environ.get("MYSQL_PORT", "3306")
    user = os.environ.get(f"{prefix}_DB_USER", f"nis_{prefix.lower()}_app")
    password = os.environ.get(f"{prefix}_DB_PASSWORD", "")
    database = os.environ.get(f"{prefix}_DB_NAME", f"nis_{prefix.lower()}")
    return (
        f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}"
        "?charset=utf8mb4"
    )


def build_downstream_urls(service: str) -> dict[str, str]:
    """本服务需要调用的其他服务地址（不含自己）。"""

    urls: dict[str, str] = {}
    for name, env_key in SERVICE_URL_ENV.items():
        if name == service:
            continue
        urls[name] = os.environ.get(env_key, f"http://127.0.0.1:{SERVICE_PORT[name]}")
    return urls


def load_settings(service: str, env_file: str | os.PathLike[str] | None = None) -> ServiceSettings:
    """读取指定服务的配置；测试可用 ``<PREFIX>_DB_URL`` 直接覆盖数据源。"""

    if service not in SERVICE_PORT:
        raise ValueError(f"未知服务：{service}")
    load_env_file(env_file)
    return ServiceSettings(
        service=service,
        app_env=os.environ.get("APP_ENV", "development"),
        log_level=os.environ.get("APP_LOG_LEVEL", "INFO"),
        db_url=build_db_url(service),
        downstream=build_downstream_urls(service),
    )
