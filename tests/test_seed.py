"""种子数据用例（Issue #7 验收：四类账号可用、口令为自适应哈希、重复执行幂等）。"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import select

from conftest import ensure_schema, import_service

DEMO_PASSWORD = "demo-pass-2026"
ADMIN_PASSWORD = "admin-pass-2026"


@pytest.fixture
def iam():
    """导入 IAM 服务并建好内存表。"""

    models, _ = import_service("iam-service")
    seed_module = importlib.import_module("app.seed")
    from nis_shared.db import Database

    database = Database("sqlite+pysqlite:///:memory:")
    ensure_schema(database)
    yield models, seed_module, database
    database.engine.dispose()


def _run(seed_module, database, *, dry_run: bool = False):  # noqa: ANN001
    return seed_module.seed(
        database,
        admin_password=ADMIN_PASSWORD,
        demo_password=DEMO_PASSWORD,
        dry_run=dry_run,
    )


def test_seed_creates_full_baseline(iam) -> None:
    models, seed_module, database = iam
    counts = _run(seed_module, database)

    assert counts == {
        "organizations": 5,
        "permissions": 18,
        "roles": 5,  # 四类标准角色 + 管理权限束
        "role_permissions": 4 + 5 + 4 + 5 + 3,  # 见 rbac 第 3 节 + 管理权限束
        "users": 8,
        "user_roles": 9,  # admin 两个角色
    }

    with database.session() as db:
        assert len(db.scalars(select(models.OrganizationUnit)).all()) == 5
        users = {u.username: u for u in db.scalars(select(models.User)).all()}
        assert set(users) == {
            "admin",
            "recon01",
            "recon02",
            "analyst01",
            "analyst02",
            "dmaker01",
            "exec01",
            "exec02",
        }
        # 口令必须是 bcrypt 哈希，不能出现明文
        for user in users.values():
            assert user.password_hash.startswith("$2b$")
            assert DEMO_PASSWORD not in user.password_hash
            assert ADMIN_PASSWORD not in user.password_hash
        assert users["admin"].password_hash != users["recon01"].password_hash


def test_seed_is_idempotent(iam) -> None:
    _, seed_module, database = iam
    _run(seed_module, database)
    second = _run(seed_module, database)
    assert all(value == 0 for value in second.values()), second


def test_seed_dry_run_rolls_back(iam) -> None:
    models, seed_module, database = iam
    _run(seed_module, database, dry_run=True)
    with database.session() as db:
        assert db.scalars(select(models.User)).all() == []
        assert db.scalars(select(models.OrganizationUnit)).all() == []


def test_standard_role_permission_matrix(iam) -> None:
    """四类标准角色的默认权限必须与 docs/rbac.md 第 3 节一致。"""

    models, seed_module, database = iam
    _run(seed_module, database)

    from nis_shared.enums import ROLE_PERMISSIONS

    with database.session() as db:
        roles = {role.code: role for role in db.scalars(select(models.Role)).all()}
        perms = {perm.id: perm.code for perm in db.scalars(select(models.Permission)).all()}
        pairs = db.scalars(select(models.RolePermission)).all()
        granted: dict[str, set[str]] = {}
        for pair in pairs:
            granted.setdefault(pair.role_id, set()).add(perms[pair.permission_id])

        for role_code, expected in ROLE_PERMISSIONS.items():
            actual = granted[roles[str(role_code)].id]
            assert actual == set(expected), f"{role_code} 权限不符：{actual ^ set(expected)}"

        admin = granted[roles[seed_module.ADMIN_ROLE_CODE].id]
        assert admin == set(seed_module.ADMIN_ROLE_PERMISSIONS)
        # 管理权限束不得含任何业务权限
        assert not {code for code in admin if code.split(":")[0] in {"recon", "analysis", "command", "execution"}}


def test_multi_role_user_gets_union(iam) -> None:
    """多角色用户的权限并集（rbac 第 1 节、验收场景 2）。"""

    models, seed_module, database = iam
    _run(seed_module, database)

    with database.session() as db:
        admin = db.scalars(select(models.User).where(models.User.username == "admin")).one()
        user_role_ids = [
            ur.role_id
            for ur in db.scalars(select(models.UserRole).where(models.UserRole.user_id == admin.id)).all()
        ]
        assert len(user_role_ids) == 2, "admin 应同时具备标准角色与管理权限束"
        perms = {
            perm.code
            for perm in db.scalars(select(models.Permission)).all()
            if any(
                rp.permission_id == perm.id and rp.role_id in user_role_ids
                for rp in db.scalars(select(models.RolePermission)).all()
            )
        }
        assert {"command:issue", "iam:manage", "organization:manage", "audit:read"} <= perms


def test_organization_paths(iam) -> None:
    models, seed_module, database = iam
    _run(seed_module, database)
    with database.session() as db:
        orgs = {org.code: org for org in db.scalars(select(models.OrganizationUnit)).all()}
        assert orgs["ORG-CMD"].path == "/ORG-CMD/"
        assert orgs["ORG-REC"].path == "/ORG-CMD/ORG-REC/"
        assert orgs["ORG-REC"].parent_id == orgs["ORG-CMD"].id


def test_password_helpers() -> None:
    from nis_shared.security import BCRYPT_ROUNDS, hash_password, needs_rehash, verify_password

    hashed = hash_password("s3cret-value")
    assert verify_password("s3cret-value", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("s3cret-value", "not-a-bcrypt-hash")
    # 哈希必须用当前配置的代价
    assert hashed.split("$")[2] == str(BCRYPT_ROUNDS).zfill(2)
    assert not needs_rehash(hashed)
    if BCRYPT_ROUNDS > 4:
        assert needs_rehash("$2b$04$abcdefghijklmnopqrstuv")


def test_seed_requires_passwords(iam) -> None:
    _, seed_module, database = iam
    with pytest.raises(ValueError):
        seed_module.seed(database, admin_password="", demo_password=DEMO_PASSWORD)
