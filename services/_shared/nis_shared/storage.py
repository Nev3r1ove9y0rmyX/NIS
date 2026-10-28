"""证据文件的受控存储（决策 D-02）。

规则（docs/service-contracts.md 第 9 节）：

- 文件本体放在服务器**受控目录**，按 ``<资源类型>/<资源 UUID>/<文件名>`` 分目录；
- 数据库只存文件名、媒体类型、大小、``sha256`` 与 ``storage_ref``，不存绝对路径；
- 下载必须经业务接口鉴权后再流式返回，禁止把受控目录挂成公开静态路径；
- 路径解析必须防目录穿越与绝对路径注入。
"""

from __future__ import annotations

import os
from pathlib import Path

from .errors import ApiError

DEFAULT_ROOT = "/var/lib/nis/evidence"


def evidence_root() -> Path:
    return Path(os.environ.get("EVIDENCE_ROOT", DEFAULT_ROOT)).resolve()


def resolve_storage_path(storage_ref: str) -> Path:
    """把 ``storage_ref`` 解析成受控目录下的绝对路径；越界或不存在一律 404。"""

    if not storage_ref:
        raise ApiError("RESOURCE_NOT_FOUND", "证据文件不存在")
    ref = Path(storage_ref)
    if ref.is_absolute() or ".." in ref.parts:
        raise ApiError("RESOURCE_NOT_FOUND", "证据文件不存在")

    root = evidence_root()
    candidate = (root / ref).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:  # 越出受控目录
        raise ApiError("RESOURCE_NOT_FOUND", "证据文件不存在") from exc

    if not candidate.is_file():
        raise ApiError("RESOURCE_NOT_FOUND", "证据文件不存在")
    return candidate
