"""数据模型与 docs/data-model.md 的一致性检查（Issue #7 验收）。"""

from __future__ import annotations

import pytest

from conftest import import_service

#: 每个持久化服务按 docs/data-model.md 必须存在的表。
EXPECTED_TABLES = {
    "iam-service": {
        "organization_units",
        "users",
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
    },
    "recon-service": {"recon_records", "recon_assignments", "recon_evidence"},
    "analysis-service": {"analysis_reports", "report_recon_links", "report_assignments"},
    "decision-service": {
        "commands",
        "command_assignments",
        "command_conflict_checks",
    },
    "execution-service": {"execution_assignments", "execution_evidence"},
    "ai-service": {"ai_requests", "ai_suggestions"},
    "audit-service": {"audit_events", "audit_trace_index"},
}

#: 只追加表：不设 version / updated_*（数据模型 1.3）。
APPEND_ONLY_TABLES = {"recon_evidence", "execution_evidence", "audit_events", "audit_trace_index"}

HEAD_COLUMNS = {"version", "created_at", "created_by", "updated_at", "updated_by"}
MUTABLE_COLUMNS = {"version", "created_by", "updated_at", "updated_by"}


@pytest.fixture(scope="module")
def metadata():
    from nis_shared.models import Base

    for service in EXPECTED_TABLES:
        import_service(service)
    return Base.metadata


def test_all_documented_tables_exist(metadata) -> None:
    for service, tables in EXPECTED_TABLES.items():
        missing = tables - set(metadata.tables)
        assert not missing, f"{service} 缺少表：{sorted(missing)}"


def test_no_undocumented_tables(metadata) -> None:
    documented = set().union(*EXPECTED_TABLES.values())
    extra = set(metadata.tables) - documented
    assert not extra, f"存在数据模型未登记的表：{sorted(extra)}"


def test_head_fields_present(metadata) -> None:
    #: 数据模型 10.2 明确用 request_id 作主键的索引表
    alternate_pk = {"audit_trace_index": "request_id"}

    for name, table in metadata.tables.items():
        columns = {column.name for column in table.columns}
        pk = alternate_pk.get(name, "id")
        assert pk in columns, f"{name} 缺少主键列 {pk}"
        if name in APPEND_ONLY_TABLES:
            assert not (columns & MUTABLE_COLUMNS), (
                f"{name} 是只追加表，不应有 {sorted(columns & MUTABLE_COLUMNS)}"
            )
        else:
            missing = HEAD_COLUMNS - columns
            assert not missing, f"{name} 缺少标准头字段：{sorted(missing)}"


def test_unique_business_keys(metadata) -> None:
    """唯一约束优先落在数据库层（数据模型 1.5）。"""

    expected_unique_columns = {
        "organization_units": ("code",),
        "users": ("username",),
        "roles": ("code",),
        "permissions": ("code",),
        "recon_records": ("record_no",),
        "analysis_reports": ("report_no",),
        "commands": ("command_no",),
    }
    for table_name, wanted in expected_unique_columns.items():
        table = metadata.tables[table_name]
        unique_single = {
            tuple(column.name for column in constraint.columns)
            for constraint in table.constraints
            if constraint.__class__.__name__ == "UniqueConstraint"
        }
        unique_single |= {
            (index.columns.keys()[0],) for index in table.indexes if index.unique and len(index.columns) == 1
        }
        assert wanted in unique_single, f"{table_name} 缺少唯一约束 {wanted}"


def test_no_cross_schema_foreign_keys(metadata) -> None:
    """跨服务引用只存 UUID，不建外键（数据模型 1.4）。"""

    #: 同 Schema 内允许的外键：{表: {被引用表}}
    internal_fks = {
        "organization_units": {"organization_units"},
        "users": {"organization_units"},
        "user_roles": {"users", "roles"},
        "role_permissions": {"roles", "permissions"},
        "recon_assignments": {"recon_records"},
        "recon_evidence": {"recon_records"},
        "report_recon_links": {"analysis_reports"},
        "report_assignments": {"analysis_reports"},
        "command_assignments": {"commands"},
        "command_conflict_checks": {"commands"},
        "execution_evidence": {"execution_assignments"},
        "ai_suggestions": {"ai_requests"},
    }
    service_tables = {name: set(tables) for name, tables in EXPECTED_TABLES.items()}
    table_service = {
        table: service for service, tables in service_tables.items() for table in tables
    }

    for table_name, table in metadata.tables.items():
        for fk in table.foreign_keys:
            target = fk.column.table.name
            assert target in internal_fks.get(table_name, set()), (
                f"{table_name} -> {target} 不在允许的同 Schema 外键清单内"
            )
            assert table_service.get(target) == table_service.get(table_name), (
                f"{table_name} 建立了跨 Schema 外键 -> {target}"
            )


def test_list_indexes_exist(metadata) -> None:
    """列表页按 (owner, status, updated_at) 建复合索引（数据模型 1.5、评审第 35 条）。"""

    expected = {
        "recon_records": ("owner_id", "status", "updated_at"),
        "analysis_reports": ("author_id", "status", "updated_at"),
        "commands": ("decision_maker_id", "status", "updated_at"),
        "execution_assignments": ("executor_id", "status", "updated_at"),
    }
    for table_name, columns in expected.items():
        table = metadata.tables[table_name]
        assert any(
            tuple(index.columns.keys()) == columns for index in table.indexes
        ), f"{table_name} 缺少复合索引 {columns}"
