#!/usr/bin/env python3
"""检查仓库内 Markdown 的相对链接是否存在，防止文档互相引用时留下死链。

规则：
- 只检查以 ](目标) 形式书写的相对路径链接；
- 跳过 http/https/mailto 和纯锚点（#开头）；
- 忽略 .git 目录与 node_modules；
- 目标带 #锚点 时只校验文件部分存在。

用法：
    python scripts/check_doc_links.py
    python scripts/check_doc_links.py --root . --quiet

退出码：0 无死链；1 存在死链。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKIP_DIRS = {".git", "node_modules", "dist", ".venv", "venv", "evidence"}


def iter_markdown(root: Path):
    for path in root.rglob("*.md"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def main() -> int:
    parser = argparse.ArgumentParser(description="检查 Markdown 相对链接")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--quiet", action="store_true", help="成功时不输出统计")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    checked = 0
    broken: list[str] = []

    for md in iter_markdown(root):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError as error:
            broken.append(f"{md.relative_to(root)}: 无法读取（{error}）")
            continue
        for raw in LINK.findall(text):
            target = raw.strip()
            if target.startswith(("http://", "https://", "mailto:", "#", "tel:")):
                continue
            file_part = target.split("#", 1)[0]
            if not file_part:
                continue
            checked += 1
            if not (md.parent / file_part).resolve().exists():
                broken.append(f"{md.relative_to(root)} -> {target}")

    if broken:
        print("发现死链：")
        for item in broken:
            print(f"  [错误] {item}")
        print(f"共检查 {checked} 条相对链接，{len(broken)} 条失效。")
        return 1

    if not args.quiet:
        print(f"相对链接检查通过：{checked} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
