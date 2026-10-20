# SOA 服务目录

版本：0.1

## 1. 服务清单

端口仅用于 DMZ 内部服务网络，除 Gateway 外不得映射至外网。

| 服务 | 目录 | 内部端口 | 数据 Schema | 健康检查 | 主责 |
|---|---|---:|---|---|---|
| API Gateway | `services/api-gateway` | 8000 | 无 | `/health/live`、`/health/ready` | A、B |
| IAM & Organization | `services/iam-service` | 8001 | `nis_iam` | `/health/live`、`/health/ready` | B |
| Reconnaissance | `services/recon-service` | 8002 | `nis_recon` | `/health/live`、`/health/ready` | B |
| Analysis | `services/analysis-service` | 8003 | `nis_analysis` | `/health/live`、`/health/ready` | B |
| Decision | `services/decision-service` | 8004 | `nis_decision` | `/health/live`、`/health/ready` | B、A |
| Execution | `services/execution-service` | 8005 | `nis_execution` | `/health/live`、`/health/ready` | B |
| AI Assistance | `services/ai-service` | 8006 | `nis_ai` | `/health/live`、`/health/ready` | B、A |
| Audit | `services/audit-service` | 8007 | `nis_audit` | `/health/live`、`/health/ready` | B、D |

## 2. API Gateway

公开前缀：`/api/v1`

主要职责：

- 统一入口和服务路由；
- 创建或透传 `X-Request-ID`；
- 转发用户 JWT 和明确的角色上下文；
- 限制请求体大小、基础限流和统一外部错误格式；
- 实现 Workflow Coordinator；
- 聚合决策员查看指令和执行结果等跨服务只读视图。

禁止事项：

- 不保存侦察、报告、指令和执行结果；
- 不直接连接业务 Schema；
- 不把内部服务地址返回浏览器；
- 不作为唯一授权点。

## 3. IAM & Organization Service

主要资源：`users`、`roles`、`permissions`、`user_roles`、`role_permissions`、`organization_units`、`organization_memberships`。

主要接口族：

- `/internal/v1/auth/*`：登录、当前身份和 Token 相关；
- `/internal/v1/users/*`：用户和状态；
- `/internal/v1/roles/*`：角色、权限及多对多关系；
- `/internal/v1/organizations/*`：组织结构；
- `/internal/v1/candidates`：按目标角色、组织和启用状态筛选候选用户。

JWT 使用非对称签名。私钥只在 IAM Service；业务服务只获得公钥。

## 4. Reconnaissance Service

主要资源：侦察记录、侦察指派、证据元数据、AI 建议引用。

主要接口族：

- `/internal/v1/recon-records`；
- `/internal/v1/recon-records/{id}/submit`；
- `/internal/v1/recon-records/{id}/assignments`；
- `/internal/v1/recon-records/{id}/authorized-view`。

提交时调用 IAM Service 验证分析员候选资格。Analysis Service 通过授权接口读取必要侦察数据。

## 5. Analysis Service

主要资源：分析报告、报告与侦察记录引用、决策员指派、AI 建议引用。

主要接口族：

- `/internal/v1/analysis-reports`；
- `/internal/v1/analysis-reports/{id}/submit`；
- `/internal/v1/analysis-reports/{id}/authorized-view`。

服务保存侦察记录 UUID 和必要快照摘要，不直接写 `nis_recon`。

## 6. Decision Service

主要资源：决策指令、冲突检查记录、执行服务引用和整体状态摘要。

主要接口族：

- `/internal/v1/commands`；
- `/internal/v1/commands/conflicts`；
- `/internal/v1/commands/{id}/issue`；
- `/internal/v1/commands/{id}/cancel`；
- `/internal/v1/commands/{id}/status`。

指令从 `draft` 进入 `issuing` 后，Execution Service 成功创建全部个人分配才进入 `issued`。

## 7. Execution Service

主要资源：个人执行分配、执行状态、执行结果和证据元数据。

主要接口族：

- `/internal/v1/assignments`；
- `/internal/v1/assignments/{id}/accept`；
- `/internal/v1/assignments/{id}/reject`；
- `/internal/v1/assignments/{id}/start`；
- `/internal/v1/assignments/{id}/complete`；
- `/internal/v1/commands/{command_id}/summary`。

## 8. AI Assistance Service

主要资源：AI 请求、建议、模型信息、人工处理结果引用。

统一接口：`POST /internal/v1/suggestions`。

请求必须声明 `stage`：`recon`、`analysis`、`decision` 或 `execution`。响应只返回建议及来源元数据，不能调用业务提交接口。

## 9. Audit Service

主要资源：不可由普通业务修改的审计事件和系统事件。

主要接口族：

- `POST /internal/v1/audit-events`；
- `GET /internal/v1/audit-events`；
- `GET /internal/v1/traces/{request_id}`。

审计事件必须包含操作者、角色上下文、服务、动作、对象、结果、时间和请求 ID，不包含密码、Token 或敏感正文。

## 10. 服务就绪标准

任何服务标记为完成前必须具备：

- 独立 Dockerfile；
- `/health/live` 与 `/health/ready`；
- OpenAPI 契约；
- 环境变量示例；
- 自己的数据库迁移（若持久化）；
- 单元测试与至少一个契约测试；
- 结构化日志和请求 ID；
- 超时、错误和依赖不可用处理；
- 不直接写其他服务 Schema 的验证。
