#!/usr/bin/env python3
"""校验 contracts/ 下的 OpenAPI 契约与共享组件库。

检查项（失败即非零退出）：
1. YAML 可解析且没有重复键（PyYAML 默认会静默覆盖重复键，这里改为报错）；
2. 必需顶层字段：openapi、info.title、info.version、paths；
3. 每个路径以 / 开头，每个操作有唯一 operationId、至少一个成功响应；
4. 路径模板中的 {参数} 在 path 或 operation 级别有对应 parameters 声明；
5. 所有 $ref 都能解析（本地 #/... 与跨文件 ../schemas/common.yaml#/...）；
6. 使用 security 的文件必须声明 securitySchemes；
7. 共享枚举文件存在且每个枚举非空、无重复值。

用法：
    python scripts/validate_contracts.py
    python scripts/validate_contracts.py --contracts contracts --quiet

依赖：PyYAML。缺少时脚本给出明确提示并以退出码 2 结束。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - 环境缺少依赖时给出可执行提示
    print(
        "缺少 PyYAML：请先安装依赖（pip install pyyaml），"
        "或使用已安装 PyYAML 的 Python 解释器运行本脚本。",
        file=sys.stderr,
    )
    raise SystemExit(2)

HTTP_METHODS = {
    "get",
    "put",
    "post",
    "delete",
    "options",
    "head",
    "patch",
    "trace",
}
SUCCESS_CODES = {"200", "201", "202", "203", "204", "205", "206"}


class DuplicateKeyLoader(yaml.SafeLoader):
    """在重复键出现时报错，而不是静默覆盖后产生错误基线。"""


def _construct_mapping(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False):
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"发现重复键 {key!r}（首次出现于第 {key_node.start_mark.line + 1} 行）",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


DuplicateKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


class Problem(dict):
    pass


def load_yaml(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    return yaml.load(text, Loader=DuplicateKeyLoader)  # noqa: S506 - 只读取仓库内文件


def resolve_pointer(document: Any, pointer: str) -> Any:
    """按 JSON Pointer 取节点，返回 (节点, 是否找到)。"""
    if pointer in ("", "/"):
        return document, True
    current = document
    for raw_part in pointer.lstrip("/").split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            return None, False
    return current, True


def walk_refs(node: Any, path: str = "#"):
    """遍历文档，产出 (ref 字符串, 所在位置)。"""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield ref, path
        for key, value in node.items():
            if key == "$ref":
                continue
            yield from walk_refs(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from walk_refs(value, f"{path}/{index}")


class Validator:
    def __init__(self, contracts_dir: Path) -> None:
        self.contracts_dir = contracts_dir
        self.openapi_dir = contracts_dir / "openapi"
        self.schemas_dir = contracts_dir / "schemas"
        self.problems: list[str] = []
        self.documents: dict[Path, Any] = {}
        self.operation_ids: dict[str, Path] = {}

    # ---------- 基础 ----------

    def fail(self, file: Path, message: str) -> None:
        try:
            relative = file.relative_to(self.contracts_dir.parent)
        except ValueError:
            relative = file
        self.problems.append(f"{relative}: {message}")

    def load_all(self) -> bool:
        files = sorted(self.openapi_dir.glob("*.yaml")) + sorted(self.schemas_dir.glob("*.yaml"))
        if not files:
            self.problems.append(f"{self.contracts_dir}: 未找到任何 .yaml 契约文件")
            return False
        ok = True
        for file in files:
            try:
                self.documents[file] = load_yaml(file)
            except yaml.YAMLError as error:
                self.fail(file, f"YAML 解析失败：{error}")
                ok = False
        return ok

    # ---------- 结构 ----------

    def check_structure(self) -> None:
        for file, document in self.documents.items():
            if self.openapi_dir not in file.parents:
                # contracts/schemas 下的共享组件库不是完整 OpenAPI 文档，
                # 只参与枚举与引用检查。
                continue
            if document is None or not isinstance(document, dict):
                self.fail(file, "文档不是映射结构")
                continue
            if not str(document.get("openapi", "")).startswith("3.1"):
                self.fail(file, "openapi 版本必须为 3.1.x")
            info = document.get("info")
            if not isinstance(info, dict):
                self.fail(file, "缺少 info")
            else:
                for field in ("title", "version"):
                    if not info.get(field):
                        self.fail(file, f"info.{field} 为空")
            if "paths" not in document:
                self.fail(file, "缺少 paths")
                continue
            self.check_paths(file, document)
            self.check_security(file, document)
            self.check_tags(file, document)

    def check_paths(self, file: Path, document: dict) -> None:
        paths = document.get("paths") or {}
        if not isinstance(paths, dict) or not paths:
            self.fail(file, "paths 为空")
            return
        defined_tags = {
            tag.get("name")
            for tag in document.get("tags", [])
            if isinstance(tag, dict) and tag.get("name")
        }
        for raw_path, path_item in paths.items():
            if not isinstance(raw_path, str) or not raw_path.startswith("/"):
                self.fail(file, f"路径 {raw_path!r} 必须以 / 开头")
                continue
            if not isinstance(path_item, dict):
                self.fail(file, f"路径 {raw_path} 的定义不是映射")
                continue
            shared_params = path_item.get("parameters") or []
            for method, operation in path_item.items():
                if method not in HTTP_METHODS:
                    continue
                if not isinstance(operation, dict):
                    self.fail(file, f"{method.upper()} {raw_path} 操作定义不是映射")
                    continue
                operation_id = operation.get("operationId")
                if not operation_id:
                    self.fail(file, f"{method.upper()} {raw_path} 缺少 operationId")
                elif operation_id in self.operation_ids:
                    first = self.operation_ids[operation_id].name
                    self.fail(
                        file,
                        f"operationId {operation_id} 与 {first} 重复",
                    )
                else:
                    self.operation_ids[operation_id] = file

                responses = operation.get("responses")
                if not isinstance(responses, dict) or not responses:
                    self.fail(file, f"{method.upper()} {raw_path} 缺少 responses")
                elif not SUCCESS_CODES.intersection(responses):
                    self.fail(file, f"{method.upper()} {raw_path} 没有成功响应")

                for tag in operation.get("tags", []) or []:
                    if tag not in defined_tags:
                        self.fail(file, f"{method.upper()} {raw_path} 使用了未声明标签 {tag!r}")

                self.check_path_parameters(file, method, raw_path, path_item, operation, shared_params)

    def check_path_parameters(
        self,
        file: Path,
        method: str,
        raw_path: str,
        path_item: dict,
        operation: dict,
        shared_params: list,
    ) -> None:
        placeholders = set()
        for segment in raw_path.split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                placeholders.add(segment[1:-1])

        declared = set()
        for params in (shared_params, operation.get("parameters") or []):
            for param in params or []:
                if not isinstance(param, dict):
                    continue
                if "$ref" in param:
                    resolved = self.resolve_ref(param["$ref"], file)
                    if resolved is None:
                        continue
                    name = resolved.get("name") if isinstance(resolved, dict) else None
                    location = resolved.get("in") if isinstance(resolved, dict) else None
                else:
                    name = param.get("name")
                    location = param.get("in")
                if location == "path" and name:
                    declared.add(name)

        missing = placeholders - declared
        if missing:
            self.fail(
                file,
                f"{method.upper()} {raw_path} 缺少路径参数声明：{', '.join(sorted(missing))}",
            )

    def check_security(self, file: Path, document: dict) -> None:
        schemes = (document.get("components") or {}).get("securitySchemes") or {}
        if document.get("security") and not schemes:
            self.fail(file, "文档声明了 security 但缺少 components.securitySchemes")
            return
        for raw_path, path_item in (document.get("paths") or {}).items():
            if not isinstance(path_item, dict):
                continue
            for method, operation in path_item.items():
                if method not in HTTP_METHODS or not isinstance(operation, dict):
                    continue
                for requirement in operation.get("security") or []:
                    for scheme_name in requirement:
                        if scheme_name not in schemes:
                            self.fail(
                                file,
                                f"{method.upper()} {raw_path} 引用了未定义的 securityScheme {scheme_name!r}",
                            )

    def check_tags(self, file: Path, document: dict) -> None:
        tags = document.get("tags")
        if tags is None:
            return
        if not isinstance(tags, list):
            self.fail(file, "tags 必须是列表")
            return
        seen = set()
        for tag in tags:
            name = tag.get("name") if isinstance(tag, dict) else None
            if not name:
                self.fail(file, "tags 中存在缺少 name 的条目")
                continue
            if name in seen:
                self.fail(file, f"tags 中重复声明 {name!r}")
            seen.add(name)

    # ---------- 引用 ----------

    def resolve_ref(self, ref: str, current_file: Path) -> Any:
        if "#" in ref:
            location, pointer = ref.split("#", 1)
        else:
            location, pointer = ref, ""
        if location:
            target_path = (current_file.parent / location).resolve()
            document = self.documents.get(target_path)
            if document is None:
                if target_path.exists():
                    try:
                        document = load_yaml(target_path)
                    except yaml.YAMLError:
                        return None
                    self.documents[target_path] = document
                else:
                    return None
        else:
            document = self.documents.get(current_file)
        node, found = resolve_pointer(document, pointer)
        return node if found else None

    def check_refs(self) -> None:
        for file, document in self.documents.items():
            for ref, where in walk_refs(document):
                if ref.startswith("#"):
                    node, found = resolve_pointer(document, ref[1:])
                    if not found:
                        self.fail(file, f"{where} 指向不存在的本地引用 {ref}")
                    continue
                location, _, pointer = ref.partition("#")
                target_path = (file.parent / location).resolve()
                if not target_path.exists():
                    self.fail(file, f"{where} 引用了不存在的文件 {ref}")
                    continue
                target_document = self.documents.get(target_path)
                if target_document is None:
                    try:
                        target_document = load_yaml(target_path)
                    except yaml.YAMLError as error:
                        self.fail(file, f"{where} 的目标文件解析失败 {ref}：{error}")
                        continue
                    self.documents[target_path] = target_document
                node, found = resolve_pointer(target_document, pointer)
                if not found:
                    self.fail(file, f"{where} 在外文件中找不到引用目标 {ref}")

    # ---------- 枚举 ----------

    def check_enums(self) -> None:
        common = self.schemas_dir / "common.yaml"
        document = self.documents.get(common.resolve())
        if document is None:
            self.fail(common, "缺少共享组件库 common.yaml")
            return
        schemas = (document.get("components") or {}).get("schemas") or {}
        if not schemas:
            self.fail(common, "components.schemas 为空")
            return
        for name, schema in schemas.items():
            if not isinstance(schema, dict):
                self.fail(common, f"schema {name} 不是映射")
                continue
            values = schema.get("enum")
            if values is None:
                continue
            if not isinstance(values, list) or not values:
                self.fail(common, f"枚举 {name} 必须是非空列表")
                continue
            if len(set(values)) != len(values):
                self.fail(common, f"枚举 {name} 含重复值")

    # ---------- 汇总 ----------

    def run(self) -> int:
        if not self.load_all():
            self.report()
            return 1
        for check in (
            self.check_structure,
            self.check_enums,
            self.check_refs,
        ):
            check()

        # check_structure 可能把外文件加入 documents，最后再查一次引用
        self.check_refs()
        self.report()
        return 0 if not self.problems else 1

    def report(self) -> None:
        files = sorted(self.openapi_dir.glob("*.yaml"))
        paths = 0
        operations = 0
        for file in files:
            document = self.documents.get(file) or {}
            for path_item in (document.get("paths") or {}).values():
                if isinstance(path_item, dict):
                    paths += 1
                    operations += sum(
                        1 for key in path_item if key in HTTP_METHODS
                    )
        print(f"契约文件：{len(files)} 个 OpenAPI 文档，{paths} 条路径，{operations} 个操作")
        print(f"共享枚举：{len((self.documents.get((self.schemas_dir / 'common.yaml').resolve()) or {}).get('components', {}).get('schemas', {}))} 个组件")
        if not self.problems:
            print("校验通过：未发现结构、引用或重复键问题。")
            return
        seen: set[str] = set()
        for problem in self.problems:
            if problem in seen:
                continue
            seen.add(problem)
            print(f"  [错误] {problem}")
        print(f"共 {len(seen)} 个问题。")


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 NIS 的 OpenAPI 契约")
    parser.add_argument(
        "--contracts",
        default=str(Path(__file__).resolve().parent.parent / "contracts"),
        help="contracts 目录，默认取仓库根下的 contracts",
    )
    parser.add_argument("--quiet", action="store_true", help="成功时不输出统计")
    args = parser.parse_args()
    validator = Validator(Path(args.contracts).resolve())
    code = validator.run()
    if args.quiet and code == 0:
        print("OK")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
