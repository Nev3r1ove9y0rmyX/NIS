"""IAM 业务逻辑：认证、权限并集、用户/角色/组织、候选接收人。

所有状态与权限判断都在这一类函数里，路由层只做参数校验与错误转换。
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    OrganizationUnit,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from nis_shared.enums import RoleCode
from nis_shared.errors import ApiError
from nis_shared.jwt_tokens import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    SigningKey,
    TokenError,
    create_token,
    decode_token,
)
from nis_shared.security import hash_password, verify_password

#: 连续失败达到该次数即临时锁定（rbac 第 4 节、错误码 ACCOUNT_LOCKED）。
MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_utc(value: datetime | None) -> datetime | None:
    return value


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


# --------------------------------------------------------------------------- 查询


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalars(select(User).where(User.username == username)).one_or_none()


def get_user_by_id(db: Session, user_id: str) -> User | None:
    return db.scalars(select(User).where(User.id == user_id)).one_or_none()


def roles_of(db: Session, user_id: str) -> tuple[str, ...]:
    """有效角色（排除已过期的限时授权），按代码排序保证输出稳定。"""

    now = _now()
    rows = db.execute(
        select(Role.code)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))
    ).all()
    return tuple(sorted({row[0] for row in rows}))


def permissions_of(db: Session, user_id: str) -> tuple[str, ...]:
    """角色权限并集；每次请求重新查询，改权限后立即生效。"""

    now = _now()
    rows = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(Role, Role.id == RolePermission.role_id)
        .join(UserRole, UserRole.role_id == Role.id)
        .where(UserRole.user_id == user_id)
        .where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))
    ).all()
    return tuple(sorted({row[0] for row in rows}))


def organization_of(db: Session, user: User) -> OrganizationUnit | None:
    return db.scalars(
        select(OrganizationUnit).where(OrganizationUnit.id == user.organization_id)
    ).one_or_none()


def organization_view(org: OrganizationUnit | None) -> dict[str, object]:
    if org is None:
        return {}
    return {
        "id": org.id,
        "code": org.code,
        "name": org.name,
        "parent_id": org.parent_id,
        "unit_type": org.unit_type,
        "is_active": bool(org.is_active),
    }


def user_view(db: Session, user: User, *, with_permissions: bool = True) -> dict[str, object]:
    view: dict[str, object] = {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "status": user.status,
        "organization": organization_view(organization_of(db, user)),
        "roles": list(roles_of(db, user.id)),
        "last_login_at": iso(user.last_login_at),
    }
    if with_permissions:
        view["permissions"] = list(permissions_of(db, user.id))
    return view


# --------------------------------------------------------------------------- 认证


def _token_pair(
    signing_key: SigningKey, user: User, roles: tuple[str, ...]
) -> dict[str, object]:
    access_minutes = int(os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    refresh_days = int(os.environ.get("REFRESH_TOKEN_EXPIRE_DAYS", "7"))
    access = create_token(
        signing_key=signing_key,
        user_id=user.id,
        roles=list(roles),
        organization_id=user.organization_id,
        token_type=ACCESS_TOKEN_TYPE,
        expires_minutes=access_minutes,
        jti=str(uuid.uuid4()),
    )
    refresh = create_token(
        signing_key=signing_key,
        user_id=user.id,
        roles=list(roles),
        organization_id=user.organization_id,
        token_type=REFRESH_TOKEN_TYPE,
        expires_minutes=refresh_days * 24 * 60,
        jti=str(uuid.uuid4()),
    )
    return {
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "Bearer",
        "expires_in": access_minutes * 60,
    }


def login(db: Session, signing_key: SigningKey, username: str, password: str) -> dict[str, object]:
    user = get_user_by_username(db, username)
    now = _now()

    if user is None:
        # 不区分「用户不存在」与「密码错误」，避免枚举账号
        raise ApiError("UNAUTHENTICATED", "用户名或密码错误")

    if user.status == "disabled":
        raise ApiError("UNAUTHENTICATED", "账号不可用")

    if user.locked_until is not None and user.locked_until > now:
        raise ApiError(
            "ACCOUNT_LOCKED",
            details={"locked_until": iso(user.locked_until)},
        )

    if not verify_password(password, user.password_hash):
        user.failed_login_count = int(user.failed_login_count or 0) + 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
            db.commit()
            raise ApiError(
                "ACCOUNT_LOCKED",
                "连续登录失败，账号已被临时锁定",
                details={"locked_until": iso(user.locked_until)},
            )
        db.commit()
        raise ApiError("UNAUTHENTICATED", "用户名或密码错误")

    # 成功：清理失败计数与过期锁定
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = now
    roles = roles_of(db, user.id)
    db.commit()
    return {"user": user_view(db, user), "token": _token_pair(signing_key, user, roles)}


def refresh(db: Session, signing_key: SigningKey, refresh_token: str) -> dict[str, object]:
    try:
        payload = decode_token(refresh_token, signing_key.public_key_pem, expected_type=REFRESH_TOKEN_TYPE)
    except TokenError as exc:
        raise ApiError("UNAUTHENTICATED", "刷新令牌无效或已过期") from exc

    user = get_user_by_id(db, payload.user_id)
    if user is None or not user.is_active:
        raise ApiError("UNAUTHENTICATED", "账号不存在或已停用")
    roles = roles_of(db, user.id)
    return _token_pair(signing_key, user, roles)


def session_view(
    db: Session,
    user: User,
    *,
    access_token: str,
    expires_in: int,
) -> dict[str, object]:
    """``/auth/me`` 的 SessionView：回显调用方已持有的访问令牌，不新签发凭证。

    契约把用户快照与令牌放在同一个 ``SessionView`` 里；内部接口只需要 ``user``，
    这里回显令牌是为了让调用方用同一套解析逻辑，不产生任何新密钥。
    """

    return {
        "user": user_view(db, user),
        "token": {
            "access_token": access_token,
            "refresh_token": "",
            "token_type": "Bearer",
            "expires_in": expires_in,
        },
    }


# --------------------------------------------------------------------------- 用户与角色


def list_users(
    db: Session,
    *,
    status: str | None,
    organization_id: str | None,
    role_code: str | None,
    page: int,
    page_size: int,
) -> dict[str, object]:
    stmt = select(User)
    if status:
        stmt = stmt.where(User.status == status)
    if organization_id:
        stmt = stmt.where(User.organization_id == organization_id)
    if role_code:
        stmt = stmt.join(UserRole, UserRole.user_id == User.id).join(
            Role, Role.id == UserRole.role_id
        ).where(Role.code == role_code)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(User.username).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return {
        "items": [user_view(db, user) for user in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def create_user(
    db: Session,
    *,
    username: str,
    password: str,
    display_name: str,
    organization_id: str,
    role_codes: list[str],
    actor_id: str,
) -> User:
    if get_user_by_username(db, username) is not None:
        raise ApiError("INVALID_REQUEST", "用户名已存在", details={"field": "username"}, status_code=409)

    org = db.scalars(
        select(OrganizationUnit).where(OrganizationUnit.id == organization_id)
    ).one_or_none()
    if org is None:
        raise ApiError("RESOURCE_NOT_FOUND", "组织不存在", details={"field": "organization_id"})

    roles = _resolve_roles(db, role_codes)
    now = _now()
    user = User(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        status="active",
        organization_id=organization_id,
        password_changed_at=now,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(user)
    db.flush()
    for role in roles:
        db.add(
            UserRole(
                user_id=user.id,
                role_id=role.id,
                granted_by=actor_id,
                granted_at=now,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
    db.commit()
    db.refresh(user)
    return user


def _resolve_roles(db: Session, role_codes: list[str]) -> list[Role]:
    codes = list(dict.fromkeys(role_codes))
    roles = db.scalars(select(Role).where(Role.code.in_(codes))).all()
    found = {role.code for role in roles}
    missing = [code for code in codes if code not in found]
    if missing:
        raise ApiError("INVALID_REQUEST", "角色不存在", details={"missing": missing})
    return list(roles)


def update_user(
    db: Session,
    user: User,
    *,
    display_name: str | None,
    organization_id: str | None,
    status: str | None,
    new_password: str | None,
    actor_id: str,
) -> User:
    if display_name is not None:
        user.display_name = display_name
    if organization_id is not None:
        org = db.scalars(
            select(OrganizationUnit).where(OrganizationUnit.id == organization_id)
        ).one_or_none()
        if org is None:
            raise ApiError("RESOURCE_NOT_FOUND", "组织不存在", details={"field": "organization_id"})
        user.organization_id = organization_id
    if status is not None:
        user.status = status
        if status != "active":
            # 停用/锁定后不再签发新令牌；已有令牌由每请求的状态检查拦截
            user.locked_until = None
    if new_password is not None:
        user.password_hash = hash_password(new_password)
        user.password_changed_at = _now()
        user.failed_login_count = 0
        user.locked_until = None
    user.updated_by = actor_id
    user.updated_at = _now()
    user.version = int(user.version or 1) + 1
    db.commit()
    db.refresh(user)
    return user


def list_user_roles(db: Session, user: User) -> list[dict[str, object]]:
    rows = db.execute(
        select(UserRole, Role)
        .join(Role, Role.id == UserRole.role_id)
        .where(UserRole.user_id == user.id)
        .order_by(Role.code)
    ).all()
    return [
        {
            "role_code": role.code,
            "granted_at": iso(binding.granted_at),
            "granted_by": binding.granted_by,
            "expires_at": iso(binding.expires_at),
        }
        for binding, role in rows
    ]


def assign_user_role(
    db: Session,
    user: User,
    *,
    role_code: str,
    expires_at: datetime | None,
    actor_id: str,
) -> dict[str, object]:
    role = db.scalars(select(Role).where(Role.code == role_code)).one_or_none()
    if role is None:
        raise ApiError("RESOURCE_NOT_FOUND", "角色不存在", details={"role_code": role_code})
    existing = db.scalars(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    ).one_or_none()
    if existing is not None:
        raise ApiError("INVALID_REQUEST", "该用户已拥有此角色", status_code=409)

    now = _now()
    binding = UserRole(
        user_id=user.id,
        role_id=role.id,
        granted_by=actor_id,
        granted_at=now,
        expires_at=expires_at,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(binding)
    db.commit()
    return {
        "role_code": role.code,
        "granted_at": iso(now),
        "granted_by": actor_id,
        "expires_at": iso(expires_at),
    }


def revoke_user_role(db: Session, user: User, role_code: str) -> None:
    role = db.scalars(select(Role).where(Role.code == role_code)).one_or_none()
    if role is None:
        raise ApiError("RESOURCE_NOT_FOUND", "角色不存在")
    binding = db.scalars(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    ).one_or_none()
    if binding is None:
        raise ApiError("RESOURCE_NOT_FOUND", "该用户没有此角色")
    db.delete(binding)
    db.commit()


def list_roles(db: Session) -> list[dict[str, object]]:
    roles = db.scalars(select(Role).order_by(Role.code)).all()
    return [role_view(db, role) for role in roles]


def role_view(db: Session, role: Role) -> dict[str, object]:
    codes = db.execute(
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role.id)
        .order_by(Permission.code)
    ).all()
    return {
        "id": role.id,
        "code": role.code,
        "name": role.name,
        "description": role.description,
        "is_system": bool(role.is_system),
        "permissions": [row[0] for row in codes],
    }


def create_role(db: Session, *, code: str, name: str, description: str | None, actor_id: str) -> Role:
    if db.scalars(select(Role).where(Role.code == code)).one_or_none() is not None:
        raise ApiError("INVALID_REQUEST", "角色代码已存在", status_code=409)
    role = Role(
        code=code,
        name=name,
        description=description,
        is_system=False,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(role)
    db.commit()
    db.refresh(role)
    return role


def replace_role_permissions(
    db: Session, role: Role, permission_codes: list[str], actor_id: str
) -> Role:
    codes = list(dict.fromkeys(permission_codes))
    perms = db.scalars(select(Permission).where(Permission.code.in_(codes))).all()
    found = {perm.code for perm in perms}
    missing = [code for code in codes if code not in found]
    if missing:
        raise ApiError("INVALID_REQUEST", "权限代码不存在", details={"missing": missing})

    existing = db.scalars(
        select(RolePermission).where(RolePermission.role_id == role.id)
    ).all()
    by_perm = {row.permission_id: row for row in existing}
    wanted_ids = {perm.id for perm in perms}
    now = _now()

    for perm in perms:
        if perm.id not in by_perm:
            db.add(
                RolePermission(
                    role_id=role.id,
                    permission_id=perm.id,
                    granted_at=now,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
    for perm_id, row in by_perm.items():
        if perm_id not in wanted_ids:
            db.delete(row)
    role.updated_by = actor_id
    role.updated_at = now
    role.version = int(role.version or 1) + 1
    db.commit()
    db.refresh(role)
    return role


def list_permissions(db: Session) -> list[dict[str, object]]:
    perms = db.scalars(select(Permission).order_by(Permission.code)).all()
    return [{"code": p.code, "name": p.name, "domain": p.domain} for p in perms]


# --------------------------------------------------------------------------- 组织


def list_organizations(db: Session) -> list[dict[str, object]]:
    orgs = db.scalars(
        select(OrganizationUnit).order_by(OrganizationUnit.sort_order, OrganizationUnit.code)
    ).all()
    return [organization_view(org) for org in orgs]


def create_organization(
    db: Session,
    *,
    code: str,
    name: str,
    parent_id: str | None,
    unit_type: str,
    sort_order: int,
    actor_id: str,
) -> OrganizationUnit:
    if db.scalars(select(OrganizationUnit).where(OrganizationUnit.code == code)).one_or_none():
        raise ApiError("INVALID_REQUEST", "组织代码已存在", status_code=409)
    parent = None
    if parent_id:
        parent = db.scalars(
            select(OrganizationUnit).where(OrganizationUnit.id == parent_id)
        ).one_or_none()
        if parent is None:
            raise ApiError("RESOURCE_NOT_FOUND", "上级组织不存在", details={"field": "parent_id"})

    org = OrganizationUnit(
        code=code,
        name=name,
        parent_id=parent.id if parent else None,
        unit_type=unit_type,
        path=f"{parent.path}{code}/" if parent else f"/{code}/",
        sort_order=sort_order,
        is_active=True,
        created_by=actor_id,
        updated_by=actor_id,
    )
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


# --------------------------------------------------------------------------- 候选接收人


def list_candidates(
    db: Session,
    *,
    target_role: str,
    source_organization_id: str | None,
    limit: int = 50,
) -> list[dict[str, object]]:
    """候选口径写死在服务端：启用账号 + 目标角色未过期 + 同组织或下级组织。"""

    now = _now()
    stmt = (
        select(User, OrganizationUnit, Role)
        .join(OrganizationUnit, OrganizationUnit.id == User.organization_id)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.status == "active")
        .where(OrganizationUnit.is_active.is_(True))
        .where(Role.code == target_role)
        .where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))
    )
    if source_organization_id:
        source = db.scalars(
            select(OrganizationUnit).where(OrganizationUnit.id == source_organization_id)
        ).one_or_none()
        if source is not None:
            stmt = stmt.where(OrganizationUnit.path.like(f"{source.path}%"))

    rows = db.execute(stmt.order_by(OrganizationUnit.sort_order, User.display_name).limit(limit)).all()
    seen: set[str] = set()
    items: list[dict[str, object]] = []
    for user, org, role in rows:
        if user.id in seen:
            continue
        seen.add(user.id)
        items.append(
            {
                "user_id": user.id,
                "display_name": user.display_name,
                "role_code": role.code,
                "organization_id": org.id,
                "organization_code": org.code,
                "organization_name": org.name,
                "online": None,
            }
        )
    return items


def resolve_users(db: Session, *, user_ids: list[str], required_role: str) -> list[dict[str, object]]:
    """提交时二次校验接收人：满足目标角色、启用、未过期才算合法。"""

    now = _now()
    wanted = list(dict.fromkeys(user_ids))
    if not wanted:
        return []
    rows = db.execute(
        select(User, Role)
        .join(UserRole, UserRole.user_id == User.id)
        .join(Role, Role.id == UserRole.role_id)
        .where(User.id.in_(wanted))
        .where(User.status == "active")
        .where(Role.code == required_role)
        .where((UserRole.expires_at.is_(None)) | (UserRole.expires_at > now))
    ).all()
    resolved = {user.id: user for user, _ in rows}
    return [
        {
            "user_id": user_id,
            "valid": user_id in resolved,
            "reason": None if user_id in resolved else "not_eligible",
            "display_name": resolved[user_id].display_name if user_id in resolved else None,
        }
        for user_id in wanted
    ]


#: 供路由层校验角色代码是否属于标准角色
STANDARD_ROLES = {str(role) for role in RoleCode}

