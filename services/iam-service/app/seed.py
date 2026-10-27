"""IAM 种子数据。

写入顺序固定为：组织 → 权限 → 角色 → 角色权限 → 用户 → 用户角色（docs/data-model.md 第 12 节）。
所有写入按唯一键判重，重复执行不会覆盖或重复插入，也不会改动已有用户口令。

命令行入口是 ``scripts/seed_data.py``；口令只从环境变量读取，绝不写入仓库。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    OrganizationUnit,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from nis_shared.db import Database
from nis_shared.enums import (
    PERMISSION_CATALOG,
    ROLE_PERMISSIONS,
    OrganizationType,
    RoleCode,
)
from nis_shared.security import hash_password

#: 组织结构（docs/demo-script.md 第 3 节）。
ORGANIZATIONS: list[dict[str, str]] = [
    {"code": "ORG-CMD", "name": "联合指挥所", "unit_type": OrganizationType.COMMAND, "parent": ""},
    {"code": "ORG-REC", "name": "侦察分队", "unit_type": OrganizationType.RECON_TEAM, "parent": "ORG-CMD"},
    {"code": "ORG-ANA", "name": "分析组", "unit_type": OrganizationType.ANALYSIS_TEAM, "parent": "ORG-CMD"},
    {"code": "ORG-DEC", "name": "决策组", "unit_type": OrganizationType.STAFF, "parent": "ORG-CMD"},
    {"code": "ORG-EXE", "name": "执行分队", "unit_type": OrganizationType.EXECUTION_TEAM, "parent": "ORG-CMD"},
]

#: 四类标准角色的显示名。
ROLE_NAMES: dict[RoleCode, str] = {
    RoleCode.RECONNAISSANCE: "侦察员",
    RoleCode.ANALYST: "分析员",
    RoleCode.DECISION_MAKER: "决策员",
    RoleCode.EXECUTOR: "执行员",
}

#: 管理权限束：rbac 第 1 节要求“管理是一组权限，授予已有标准业务角色的用户”，
#: 因此用一个只装管理/审计权限的角色承载，不新增第五种业务角色。
ADMIN_ROLE_CODE = "administrator"
ADMIN_ROLE_PERMISSIONS = ("iam:manage", "organization:manage", "audit:read")

#: 演示账号（docs/demo-script.md 第 3 节）。admin 同时具备 decision_maker 标准角色。
DEMO_USERS: list[dict[str, object]] = [
    {"username": "admin", "display_name": "系统管理员", "org": "ORG-DEC", "roles": [RoleCode.DECISION_MAKER, ADMIN_ROLE_CODE], "admin": True},
    {"username": "recon01", "display_name": "侦察员甲", "org": "ORG-REC", "roles": [RoleCode.RECONNAISSANCE]},
    {"username": "recon02", "display_name": "侦察员乙", "org": "ORG-REC", "roles": [RoleCode.RECONNAISSANCE]},
    {"username": "analyst01", "display_name": "分析员甲", "org": "ORG-ANA", "roles": [RoleCode.ANALYST]},
    {"username": "analyst02", "display_name": "分析员乙", "org": "ORG-ANA", "roles": [RoleCode.ANALYST]},
    {"username": "dmaker01", "display_name": "决策员甲", "org": "ORG-DEC", "roles": [RoleCode.DECISION_MAKER]},
    {"username": "exec01", "display_name": "执行员甲", "org": "ORG-EXE", "roles": [RoleCode.EXECUTOR]},
    {"username": "exec02", "display_name": "执行员乙", "org": "ORG-EXE", "roles": [RoleCode.EXECUTOR]},
]

#: 种子写入的 created_by/updated_by。种子不是某个用户的操作，审计上以固定系统 UUID 表示，
#: 不用服务账号冒充最终操作者（docs/service-contracts.md 第 7 节）。
SYSTEM_ACTOR = "00000000-0000-0000-0000-000000000000"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def seed(
    database: Database,
    *,
    admin_password: str,
    demo_password: str,
    system_actor: str = SYSTEM_ACTOR,
    dry_run: bool = False,
) -> dict[str, int]:
    """写入种子数据并返回各类新增数量。``dry_run`` 时全部回滚。"""

    if not admin_password or not demo_password:
        raise ValueError("缺少口令：admin 与演示账号口令必须由调用方注入")

    counts = {
        "organizations": 0,
        "permissions": 0,
        "roles": 0,
        "role_permissions": 0,
        "users": 0,
        "user_roles": 0,
    }
    now = _now()

    with database.session() as db:
        _seed_organizations(db, counts, system_actor)
        _seed_permissions(db, counts, system_actor)
        role_by_code = _seed_roles(db, counts, system_actor)
        _seed_role_permissions(db, counts, system_actor, role_by_code, now)
        user_by_name, org_by_code = _seed_users(
            db, counts, system_actor, admin_password, demo_password, now
        )
        _seed_user_roles(db, counts, system_actor, user_by_name, role_by_code, now)
        if dry_run:
            db.rollback()
    return counts


def _seed_organizations(db: Session, counts: dict[str, int], actor: str) -> None:
    existing = {org.code: org for org in db.scalars(select(OrganizationUnit)).all()}
    for spec in ORGANIZATIONS:
        if spec["code"] in existing:
            continue
        parent = existing.get(spec["parent"])
        unit = OrganizationUnit(
            code=spec["code"],
            name=spec["name"],
            unit_type=str(spec["unit_type"]),
            parent_id=parent.id if parent else None,
            path=f"{parent.path}{spec['code']}/" if parent else f"/{spec['code']}/",
            is_active=True,
            created_by=actor,
            updated_by=actor,
        )
        db.add(unit)
        db.flush()
        existing[spec["code"]] = unit
        counts["organizations"] += 1


def _seed_permissions(db: Session, counts: dict[str, int], actor: str) -> None:
    existing = {perm.code for perm in db.scalars(select(Permission)).all()}
    for code, domain in PERMISSION_CATALOG.items():
        if code in existing:
            continue
        db.add(
            Permission(
                code=code, name=code, domain=str(domain), created_by=actor, updated_by=actor
            )
        )
        counts["permissions"] += 1
    db.flush()


def _seed_roles(db: Session, counts: dict[str, int], actor: str) -> dict[str, Role]:
    roles = {role.code: role for role in db.scalars(select(Role)).all()}
    for role_code, display_name in ROLE_NAMES.items():
        if str(role_code) in roles:
            continue
        role = Role(
            code=str(role_code),
            name=display_name,
            description="标准业务角色（种子创建，不允许删除）",
            is_system=True,
            created_by=actor,
            updated_by=actor,
        )
        db.add(role)
        db.flush()
        roles[str(role_code)] = role
        counts["roles"] += 1
    if ADMIN_ROLE_CODE not in roles:
        role = Role(
            code=ADMIN_ROLE_CODE,
            name="管理权限束",
            description="只包含 iam:manage / organization:manage / audit:read，不含业务权限",
            is_system=False,
            created_by=actor,
            updated_by=actor,
        )
        db.add(role)
        db.flush()
        roles[ADMIN_ROLE_CODE] = role
        counts["roles"] += 1
    return roles


def _seed_role_permissions(
    db: Session,
    counts: dict[str, int],
    actor: str,
    roles: dict[str, Role],
    now: datetime,
) -> None:
    perms = {perm.code: perm for perm in db.scalars(select(Permission)).all()}
    existing = {(rp.role_id, rp.permission_id) for rp in db.scalars(select(RolePermission)).all()}
    grants: dict[str, tuple[str, ...]] = {
        str(role_code): codes for role_code, codes in ROLE_PERMISSIONS.items()
    }
    grants[ADMIN_ROLE_CODE] = ADMIN_ROLE_PERMISSIONS
    for role_code, perm_codes in grants.items():
        role = roles[role_code]
        for perm_code in perm_codes:
            perm = perms[perm_code]
            if (role.id, perm.id) in existing:
                continue
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=perm.id,
                    granted_at=now,
                    created_by=actor,
                    updated_by=actor,
                )
            )
            existing.add((role.id, perm.id))
            counts["role_permissions"] += 1


def _seed_users(
    db: Session,
    counts: dict[str, int],
    actor: str,
    admin_password: str,
    demo_password: str,
    now: datetime,
) -> tuple[dict[str, User], dict[str, OrganizationUnit]]:
    users = {user.username: user for user in db.scalars(select(User)).all()}
    orgs = {org.code: org for org in db.scalars(select(OrganizationUnit)).all()}
    for spec in DEMO_USERS:
        username = str(spec["username"])
        if username in users:
            continue
        password = admin_password if spec.get("admin") else demo_password
        user = User(
            username=username,
            display_name=str(spec["display_name"]),
            password_hash=hash_password(password),
            status="active",
            organization_id=orgs[str(spec["org"])].id,
            password_changed_at=now,
            created_by=actor,
            updated_by=actor,
        )
        db.add(user)
        db.flush()
        users[username] = user
        counts["users"] += 1
    return users, orgs


def _seed_user_roles(
    db: Session,
    counts: dict[str, int],
    actor: str,
    users: dict[str, User],
    roles: dict[str, Role],
    now: datetime,
) -> None:
    existing = {(ur.user_id, ur.role_id) for ur in db.scalars(select(UserRole)).all()}
    for spec in DEMO_USERS:
        user = users[str(spec["username"])]
        for role_code in spec["roles"]:  # type: ignore[union-attr]
            role = roles[str(role_code)]
            if (user.id, role.id) in existing:
                continue
            db.add(
                UserRole(
                    user_id=user.id,
                    role_id=role.id,
                    granted_by=actor,
                    granted_at=now,
                    created_by=actor,
                    updated_by=actor,
                )
            )
            existing.add((user.id, role.id))
            counts["user_roles"] += 1
