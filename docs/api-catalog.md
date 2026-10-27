# 接口清单（API Catalog）

版本：0.1（接口与数据基线）

状态：A 依据 [公共契约](../contracts/openapi/api-gateway.yaml) 整理，B/C/D 评审后冻结。

本清单是接口的**人读索引**，唯一权威定义仍是 `contracts/openapi/api-gateway.yaml`。
两者不一致时以契约为准，并立即建立 Issue 修正清单。字段、枚举和错误码定义见
[共享组件库](../contracts/schemas/common.yaml)、[服务契约规范](service-contracts.md)
和[数据模型](data-model.md)。

校验命令（修改契约后必须执行）：

```bash
python scripts/validate_contracts.py
```

## 1. 通用约定

| 项目 | 约定 |
|---|---|
| 公共前缀 | `/api/v1`；健康检查在根路径 `/health/*` |
| 认证 | `Authorization: Bearer <JWT>`；一次登录，会话内不重复认证 |
| 角色上下文 | `X-Role-Context`（可选），必须属于 Token 中的有效角色 |
| 追踪 | `X-Request-ID` 由 Gateway 生成或透传，全链路一致 |
| 幂等 | 关键提交使用 `Idempotency-Key`，同键同请求返回原结果 |
| 分页 | `page`（默认 1）、`page_size`（默认 20，最大 100），响应含 `total` |
| 并发 | 可编辑资源提交 `expected_version`，旧版本返回 `409 VERSION_CONFLICT` |
| 错误 | 统一 `{code, message, request_id, details}`，错误码见服务契约规范第 3 节 |
| 时间 | ISO 8601 UTC，例如 `2026-10-16T08:30:00Z` |

响应体只返回业务字段；密码、Token、数据库连接串、内部地址和堆栈不得出现在任何
响应或日志中。

## 2. 公共接口清单

共 50 个操作。表中“幂等”列表示该操作要求 `Idempotency-Key`。

| # | 方法 | 路径 | operationId | 所需权限 | 幂等 | 主要状态码 |
|---:|---|---|---|---|:---:|---|
| 1 | POST | `/auth/login` | `login` | —（公开） | — | 200、400、401、423 |
| 2 | POST | `/auth/refresh` | `refreshToken` | —（公开） | — | 200、401 |
| 3 | POST | `/auth/logout` | `logout` | 会话有效即可 | — | 204、401 |
| 4 | GET | `/auth/me` | `getCurrentUser` | 会话有效即可 | — | 200、401 |
| 5 | GET | `/organizations` | `listOrganizations` | 会话有效即可 | — | 200、401 |
| 6 | GET | `/candidates` | `listCandidates` | 会话有效即可 | — | 200、400、401 |
| 7 | POST | `/admin/organizations` | `createOrganization` | organization:manage | 是 | 201、403、409、422 |
| 8 | GET | `/admin/users` | `listUsers` | iam:manage | — | 200、401、403 |
| 9 | POST | `/admin/users` | `createUser` | iam:manage | 是 | 201、400、403、409 |
| 10 | GET | `/admin/users/{user_id}` | `getUser` | iam:manage | — | 200、403、404 |
| 11 | PATCH | `/admin/users/{user_id}` | `updateUser` | iam:manage | — | 200、403、404、409、422 |
| 12 | GET | `/admin/users/{user_id}/roles` | `listUserRoles` | iam:manage | — | 200、403 |
| 13 | POST | `/admin/users/{user_id}/roles` | `assignUserRole` | iam:manage | — | 201、403、404、409 |
| 14 | DELETE | `/admin/users/{user_id}/roles/{role_code}` | `revokeUserRole` | iam:manage | — | 204、403、404 |
| 15 | GET | `/admin/roles` | `listRoles` | iam:manage | — | 200、403 |
| 16 | POST | `/admin/roles` | `createRole` | iam:manage | — | 201、403、409 |
| 17 | PUT | `/admin/roles/{role_id}/permissions` | `replaceRolePermissions` | iam:manage | — | 200、403、404、422 |
| 18 | GET | `/admin/permissions` | `listPermissions` | iam:manage | — | 200、403 |
| 19 | GET | `/recon-records` | `listReconRecords` | recon:read_assigned（本人或被指派） | — | 200、401、403 |
| 20 | POST | `/recon-records` | `createReconRecord` | recon:create | 是 | 201、400、403、409 |
| 21 | GET | `/recon-records/{record_id}` | `getReconRecord` | recon:read_assigned（本人或被指派） | — | 200、403、404 |
| 22 | PATCH | `/recon-records/{record_id}` | `updateReconRecord` | recon:edit_own_draft | — | 200、403、404、409、422 |
| 23 | POST | `/recon-records/{record_id}/submit` | `submitReconRecord` | recon:submit | 是 | 200、400、403、404、409、502 |
| 24 | GET | `/analysis-reports` | `listAnalysisReports` | analysis:read_assigned | — | 200、401、403 |
| 25 | POST | `/analysis-reports` | `createAnalysisReport` | analysis:create | 是 | 201、400、403、409 |
| 26 | GET | `/analysis-reports/{report_id}` | `getAnalysisReport` | analysis:read_assigned | — | 200、403、404 |
| 27 | PATCH | `/analysis-reports/{report_id}` | `updateAnalysisReport` | analysis:edit_own_draft | — | 200、403、404、409、422 |
| 28 | POST | `/analysis-reports/{report_id}/submit` | `submitAnalysisReport` | analysis:submit | 是 | 200、400、403、404、409、422、502 |
| 29 | GET | `/commands` | `listCommands` | command:read_assigned | — | 200、401、403 |
| 30 | POST | `/commands` | `createCommand` | command:create | 是 | 201、400、403、409 |
| 31 | GET | `/commands/conflicts` | `checkCommandConflicts` | command:issue | — | 200、403 |
| 32 | GET | `/commands/{command_id}` | `getCommand` | command:read_assigned | — | 200、403、404 |
| 33 | PATCH | `/commands/{command_id}` | `updateCommand` | command:create（本人草稿） | — | 200、403、404、409、422 |
| 34 | POST | `/commands/{command_id}/issue` | `issueCommand` | command:issue | 是 | 200、400、403、404、409、502 |
| 35 | POST | `/commands/{command_id}/cancel` | `cancelCommand` | command:issue | — | 200、403、404、409 |
| 36 | GET | `/commands/{command_id}/status` | `getCommandStatus` | command:read_assigned | — | 200、403、404 |
| 37 | GET | `/commands/{command_id}/results` | `listCommandResults` | command:read_assigned | — | 200、403、404 |
| 38 | GET | `/assignments` | `listAssignments` | command:read_assigned（本人分配） | — | 200、401、403 |
| 39 | GET | `/assignments/{assignment_id}` | `getAssignment` | command:read_assigned（本人分配） | — | 200、403、404 |
| 40 | POST | `/assignments/{assignment_id}/accept` | `acceptAssignment` | execution:respond | — | 200、403、404、409 |
| 41 | POST | `/assignments/{assignment_id}/reject` | `rejectAssignment` | execution:respond | — | 200、403、404、409、422 |
| 42 | POST | `/assignments/{assignment_id}/start` | `startAssignment` | execution:update | — | 200、403、404、409 |
| 43 | POST | `/assignments/{assignment_id}/complete` | `completeAssignment` | execution:submit | 是 | 200、400、403、404、409 |
| 44 | POST | `/ai/suggestions` | `createAISuggestion` | ai:suggest | — | 200、400、403、503、504 |
| 45 | GET | `/ai/suggestions/{suggestion_id}` | `getAISuggestion` | ai:suggest | — | 200、403、404 |
| 46 | POST | `/ai/suggestions/{suggestion_id}/decision` | `decideAISuggestion` | ai:suggest | — | 200、403、404、409、422 |
| 47 | GET | `/audit-events` | `listAuditEvents` | audit:read | — | 200、401、403 |
| 48 | GET | `/audit-events/traces/{request_id}` | `getAuditTrace` | audit:read | — | 200、403、404 |
| 49 | GET | `/health/live` | `gatewayLive` | —（公开） | — | 200 |
| 50 | GET | `/health/ready` | `gatewayReady` | —（公开） | — | 200、503 |

## 3. 角色与接口的对应关系

权限代码与资源范围规则见 [rbac.md](rbac.md)。下表中的权限是“必要条件”，不是
“充分条件”：每个请求仍要校验资源所有权、指派关系、组织范围和资源状态。

| 角色 | 主资源 | 允许操作 | 明确禁止 | 主要权限 |
|---|---|---|---|---|
| 侦察员 | 侦察记录 | 列表、详情、创建、编辑草稿、提交并选择分析员 | 不能读报告、指令、执行结果 | `recon:*` |
| 分析员 | 分析报告 | 读取被指派侦察记录、报告创建/编辑/提交并选择决策员 | 不能下达指令、不能看他人报告草稿 | `analysis:*、recon:read_assigned` |
| 决策员 | 决策指令 | 报告读取、指令创建/下达/取消、状态与结果聚合查看 | 不能改写报告正文、不能提交执行结果 | `command:*、analysis:read_assigned` |
| 执行员 | 执行分配 | 本人分配列表与详情、接收/拒绝、开始、提交结果 | 不能看他人分配明细、不能改指令内容 | `execution:respond/update/submit` |
| 管理权限持有者 | 用户与权限 | 用户、角色、权限、组织配置 | 默认不含业务内容改写权 | `iam:manage、organization:manage` |

## 4. 内部服务接口

内部接口只在 DMZ 容器网络内可达，不做端口映射，浏览器不得直接调用。

| 服务 | 端口 | 主要接口族 | 契约文件 |
|---|---:|---|---|
| API Gateway | 8000 | 公开 `/api/v1/*` 路由与编排 | [api-gateway.yaml](../contracts/openapi/api-gateway.yaml) |
| IAM & Organization | 8001 | `/internal/v1/auth/*`、`/users/*`、`/roles/*`、`/organizations/*`、`/candidates`、`/users/resolve`、`/auth/public-keys` | [iam-service.yaml](../contracts/openapi/iam-service.yaml) |
| Reconnaissance | 8002 | `/internal/v1/recon-records/*`、`confirm-submission`、`mark-compensation`、`authorized-view` | [recon-service.yaml](../contracts/openapi/recon-service.yaml) |
| Analysis | 8003 | `/internal/v1/analysis-reports/*`、`confirm-submission`、`decision-state`、`authorized-view` | [analysis-service.yaml](../contracts/openapi/analysis-service.yaml) |
| Decision | 8004 | `/internal/v1/commands/*`、`conflicts`、`issue`、`confirm-issue`、`cancel`、`assignment-state` | [decision-service.yaml](../contracts/openapi/decision-service.yaml) |
| Execution | 8005 | `/internal/v1/assignments/*`、`/commands/{id}/summary` | [execution-service.yaml](../contracts/openapi/execution-service.yaml) |
| AI Assistance | 8006 | `/internal/v1/suggestions`、`/suggestions/{id}/decision` | [ai-service.yaml](../contracts/openapi/ai-service.yaml) |
| Audit | 8007 | `POST/GET /internal/v1/audit-events`、`/traces/{request_id}` | [audit-service.yaml](../contracts/openapi/audit-service.yaml) |

跨服务调用规则：

1. 浏览器只调用 Gateway；Gateway 转发 `Authorization`、`X-Request-ID`、`X-Role-Context`
   和 `Idempotency-Key`，但不代替下游授权；
2. 下游服务必须独立验签 JWT、校验权限、资源范围和状态；
3. 跨服务写操作必须幂等；失败时保留可识别的中间状态，不假装成功；
4. 服务间不共享数据库账号，不跨 Schema 写入。

## 5. 关键提交的幂等与状态约束

| 操作 | 幂等键来源 | 允许的当前状态 | 成功后状态 | 重复请求行为 |
|---|---|---|---|---|
| 提交侦察记录 | 客户端生成 | `draft` | `submitting` → `assigned` | 返回原记录，不重复创建指派 |
| 提交分析报告 | 客户端生成 | `draft` 且 AI 内容已确认 | `submitting` → `assigned` | 返回原报告 |
| 下达指令 | 客户端生成 | `draft` 且冲突已确认 | `issuing` → `issued` | 返回原指令，不重复建分配 |
| 创建执行分配 | Coordinator 复用父请求 | 指令为 `issuing` | 分配 `pending` | 返回已存在的分配 |
| 提交执行结果 | 客户端生成 | `accepted`/`executing` | `completed`/`failed` | 返回原结果或 `409` |

## 6. 与需求追踪的对应

| 接口族 | 需求编号 | 验收用例 |
|---|---|---|
| `/auth/*`、`/admin/*`、`/candidates` | FR-AUTH-001~005、FR-ORG-001~002 | TC-B08、TC-B09、TC-B10、TC-B11 |
| `/recon-records/*` | FR-RECON-001~004 | TC-B12（侦察段） |
| `/analysis-reports/*` | FR-ANALYSIS-001~005 | TC-B12（分析段） |
| `/commands/*` | FR-DECISION-001~005 | TC-B12（决策段） |
| `/assignments/*` | FR-EXEC-001~004 | TC-B12（执行段） |
| `/ai/suggestions/*` | FR-*-002/003、NFR-AI-001 | TC-B13 |
| `/audit-events/*` | FR-AUDIT-001~003 | TC-B02 |
| `/health/*`、`/candidates` | NFR-SOA-001~005、FR-ORG-002 | TC-SOA01~05、TC-B15 |

完整映射见 [需求追踪矩阵](traceability.md)。

## 7. 变更规则

1. 契约文件修改后必须先跑 `scripts/validate_contracts.py`，通过后再提交；
2. 破坏兼容性的修改（改字段名、改枚举、改状态、改路径）必须建立变更 Issue，并按
   [服务契约规范](service-contracts.md) 第 8 节由 A 批准；
3. 接口变更必须同步更新本清单、数据模型、前端页面状态和测试用例；
4. 禁止先改服务返回结构、再让其他成员被动适配。
