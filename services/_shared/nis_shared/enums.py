"""全部枚举与状态代码。

取值必须与 ``contracts/schemas/common.yaml`` 和 ``docs/data-model.md`` 第 3 节完全一致；
数据库以 ``VARCHAR(32)`` 保存代码值，不使用 MySQL ``ENUM``（数据模型第 3 节）。
"""

from __future__ import annotations

from enum import StrEnum


class RoleCode(StrEnum):
    RECONNAISSANCE = "reconnaissance"
    ANALYST = "analyst"
    DECISION_MAKER = "decision_maker"
    EXECUTOR = "executor"


class Priority(StrEnum):
    NORMAL = "normal"
    URGENT = "urgent"


class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class Credibility(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNVERIFIED = "unverified"


class ReconStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTING = "submitting"
    ASSIGNED = "assigned"
    UNDER_ANALYSIS = "under_analysis"
    ANALYZED = "analyzed"
    REJECTED = "rejected"
    COMPENSATION_REQUIRED = "compensation_required"


class ReportStatus(StrEnum):
    DRAFT = "draft"
    SUBMITTING = "submitting"
    ASSIGNED = "assigned"
    UNDER_DECISION = "under_decision"
    DECIDED = "decided"
    REJECTED = "rejected"
    COMPENSATION_REQUIRED = "compensation_required"


class CommandStatus(StrEnum):
    DRAFT = "draft"
    ISSUING = "issuing"
    ISSUED = "issued"
    PARTIALLY_ACCEPTED = "partially_accepted"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    PARTIALLY_COMPLETED = "partially_completed"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    COMPENSATION_REQUIRED = "compensation_required"


class AssignmentStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class AssignmentOutcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class TargetHandlerStatus(StrEnum):
    """``recon_assignments`` / ``report_assignments`` 的处理状态。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AIStage(StrEnum):
    RECON = "recon"
    ANALYSIS = "analysis"
    DECISION = "decision"
    EXECUTION = "execution"


class AISuggestionStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class AuditEventType(StrEnum):
    USER_OPERATION = "user_operation"
    SYSTEM_EVENT = "system_event"
    SECURITY_EVENT = "security_event"


class AuditResult(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"


class OrganizationType(StrEnum):
    COMMAND = "command"
    STAFF = "staff"
    RECON_TEAM = "recon_team"
    ANALYSIS_TEAM = "analysis_team"
    EXECUTION_TEAM = "execution_team"


class SourceType(StrEnum):
    OSINT = "osint"
    SENSOR = "sensor"
    REPORT = "report"
    DOCUMENT = "document"
    OTHER = "other"


class PermissionDomain(StrEnum):
    RECON = "recon"
    ANALYSIS = "analysis"
    COMMAND = "command"
    EXECUTION = "execution"
    AI = "ai"
    AUDIT = "audit"
    IAM = "iam"
    ORGANIZATION = "organization"


#: RBAC 第 2 节的 18 个权限代码（权限 → 域）。
PERMISSION_CATALOG: dict[str, PermissionDomain] = {
    "recon:create": PermissionDomain.RECON,
    "recon:edit_own_draft": PermissionDomain.RECON,
    "recon:submit": PermissionDomain.RECON,
    "recon:read_assigned": PermissionDomain.RECON,
    "analysis:create": PermissionDomain.ANALYSIS,
    "analysis:edit_own_draft": PermissionDomain.ANALYSIS,
    "analysis:submit": PermissionDomain.ANALYSIS,
    "analysis:read_assigned": PermissionDomain.ANALYSIS,
    "command:create": PermissionDomain.COMMAND,
    "command:issue": PermissionDomain.COMMAND,
    "command:read_assigned": PermissionDomain.COMMAND,
    "execution:respond": PermissionDomain.EXECUTION,
    "execution:update": PermissionDomain.EXECUTION,
    "execution:submit": PermissionDomain.EXECUTION,
    "ai:suggest": PermissionDomain.AI,
    "audit:read": PermissionDomain.AUDIT,
    "iam:manage": PermissionDomain.IAM,
    "organization:manage": PermissionDomain.ORGANIZATION,
}

#: RBAC 第 3 节：四类标准角色的默认权限。
ROLE_PERMISSIONS: dict[RoleCode, tuple[str, ...]] = {
    RoleCode.RECONNAISSANCE: (
        "recon:create",
        "recon:edit_own_draft",
        "recon:submit",
        # 侦察员也需要读权限，但资源范围限定为「本人记录」（rbac 第 3 节矩阵）
        "recon:read_assigned",
        "ai:suggest",
    ),
    RoleCode.ANALYST: (
        "recon:read_assigned",
        "analysis:create",
        "analysis:edit_own_draft",
        "analysis:submit",
        # 分析员要读回自己写的报告（rbac 第 3 节矩阵「本人」列）
        "analysis:read_assigned",
        "ai:suggest",
    ),
    RoleCode.DECISION_MAKER: (
        "analysis:read_assigned",
        "command:create",
        "command:issue",
        # 决策员要读回自己创建的指令与各执行员状态
        "command:read_assigned",
        "ai:suggest",
    ),
    RoleCode.EXECUTOR: (
        "command:read_assigned",
        "execution:respond",
        "execution:update",
        "execution:submit",
        "ai:suggest",
    ),
}
