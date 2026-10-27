"""``nis_iam`` Schema：用户、角色、权限与组织。

逐列对应 ``docs/data-model.md`` 第 4 节。跨服务引用（业务表中的用户 UUID）不加外键。
"""

from __future__ import annotations

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import relationship

from nis_shared.enums import OrganizationType, UserStatus
from nis_shared.models import Base, DateTime3, HeadFieldsMixin, new_uuid, utcnow, uuid_pk


class OrganizationUnit(Base, HeadFieldsMixin):
    __tablename__ = "organization_units"

    id = uuid_pk()
    parent_id = Column(String(36), ForeignKey("organization_units.id"), nullable=True)
    code = Column(String(64), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    unit_type = Column(String(32), nullable=False, default=OrganizationType.COMMAND.value)
    #: 物化路径 ``/root/child/``，用于一次取子树（候选筛选的组织规则）。
    path = Column(String(512), nullable=False)
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    is_active = Column(Boolean, nullable=False, default=True, server_default="1")

    children = relationship("OrganizationUnit", backref="parent", remote_side=[id])

    __table_args__ = (
        Index("ix_organization_units_parent_id", "parent_id"),
        Index("ix_organization_units_path", "path"),
    )


class User(Base, HeadFieldsMixin):
    __tablename__ = "users"

    id = uuid_pk()
    username = Column(String(64), nullable=False, unique=True)
    #: bcrypt 自适应哈希；禁止明文与可逆加密。
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default=UserStatus.ACTIVE.value, server_default="active")
    organization_id = Column(
        String(36), ForeignKey("organization_units.id"), nullable=False
    )
    failed_login_count = Column(Integer, nullable=False, default=0, server_default="0")
    locked_until = Column(DateTime3, nullable=True)
    last_login_at = Column(DateTime3, nullable=True)
    password_changed_at = Column(DateTime3, nullable=True)

    organization = relationship("OrganizationUnit", lazy="joined")

    __table_args__ = (Index("ix_users_organization_status", "organization_id", "status"),)

    @property
    def is_active(self) -> bool:
        return self.status == UserStatus.ACTIVE.value


class Role(Base, HeadFieldsMixin):
    __tablename__ = "roles"

    id = uuid_pk()
    code = Column(String(32), nullable=False, unique=True)
    name = Column(String(64), nullable=False)
    description = Column(String(255), nullable=True)
    #: 四类标准角色为 1，不允许删除（种子脚本据此判重与保护）。
    is_system = Column(Boolean, nullable=False, default=False, server_default="0")


class Permission(Base, HeadFieldsMixin):
    __tablename__ = "permissions"

    id = uuid_pk()
    code = Column(String(64), nullable=False, unique=True)
    name = Column(String(64), nullable=False)
    domain = Column(String(32), nullable=False)


class UserRole(Base, HeadFieldsMixin):
    __tablename__ = "user_roles"

    id = Column(String(36), primary_key=True, default=new_uuid)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    role_id = Column(String(36), ForeignKey("roles.id"), nullable=False)
    granted_by = Column(String(36), nullable=False)
    granted_at = Column(DateTime3, nullable=False, default=utcnow)
    #: 限时角色预留：到期即视为无效（rbac 第 4 节第 7 条）。
    expires_at = Column(DateTime3, nullable=True)

    __table_args__ = (
        Index("uq_user_roles_user_role", "user_id", "role_id", unique=True),
        Index("ix_user_roles_role_id", "role_id"),
        Index("ix_user_roles_expires_at", "expires_at"),
    )


class RolePermission(Base, HeadFieldsMixin):
    __tablename__ = "role_permissions"

    id = Column(String(36), primary_key=True, default=new_uuid)
    role_id = Column(String(36), ForeignKey("roles.id"), nullable=False)
    permission_id = Column(String(36), ForeignKey("permissions.id"), nullable=False)
    granted_at = Column(DateTime3, nullable=False, default=utcnow)

    __table_args__ = (
        Index("uq_role_permissions_role_permission", "role_id", "permission_id", unique=True),
        Index("ix_role_permissions_permission_id", "permission_id"),
    )
