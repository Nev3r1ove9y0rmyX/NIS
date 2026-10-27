# services

后端服务目录，主责 B，接口契约见 [公共契约](../contracts/openapi/api-gateway.yaml) 与
各服务内部契约。服务划分、端口和数据所有权以
[服务目录](../docs/service-catalog.md)、[数据所有权](../docs/data-ownership.md) 为准。

## 目录约定

```text
services/
  api-gateway/       8000   路由、请求 ID、编排；无数据库
  iam-service/       8001   nis_iam
  recon-service/     8002   nis_recon
  analysis-service/  8003   nis_analysis
  decision-service/  8004   nis_decision
  execution-service/ 8005   nis_execution
  ai-service/        8006   nis_ai（可降级）
  audit-service/     8007   nis_audit（只追加）
```

每个服务目录至少包含：

```text
Dockerfile
pyproject.toml 或 requirements.txt
app/
  main.py        应用入口、路由注册、异常处理
  api/           路由层，只做参数校验与调用
  domain/        业务规则与状态转换
  db/            模型、会话、迁移（alembic/）
  clients/       调用其他服务的客户端，带超时与有限重试
tests/
  test_*.py      单元与接口测试
```

## 实现约束

1. 只读写自己 Schema；跨服务数据通过 HTTP 调用，禁止跨 Schema JOIN。
2. 每个服务独立验签 JWT 并校验权限、资源范围和状态，不依赖 Gateway 授权。
3. 关键提交实现幂等：同用户、同端点、同 `Idempotency-Key`、等价请求返回原结果。
4. 状态转换只在事务内完成，失败不留下半完成状态；无法自动恢复时置
   `compensation_required` 并写审计。
5. 每个服务提供 `/health/live` 与 `/health/ready`；就绪检查覆盖数据库与必需依赖。
6. 结构化日志包含 `request_id`，不打印密码、Token、连接串。
7. 修改对外字段、枚举或状态前，先改契约并让 CI 通过，再改实现。

## 与契约的一致性检查

提交前运行：

```bash
python scripts/validate_contracts.py
```

契约测试（B 的 P1 任务）应覆盖：响应字段与契约同名、错误码在契约表内、
权限缺失返回 403、非法状态返回 409、重复幂等请求返回原结果。

## 认证与授权（Issue #8 起可用）

一次登录、非对称签名 JWT、每请求权限校验。统一约定：

| 环节 | 约定 |
|---|---|
| 令牌 | IAM 用 RS256 私钥签发；业务服务只拿公钥（`GET /internal/v1/auth/public-keys`，按 `kid` 缓存 300 秒） |
| 验签 | 每个业务服务**本地验签**，不信任 Gateway 传来的用户头（`docs/service-contracts.md` 第 7 节） |
| 权限 | JWT 只放身份与角色；权限每次请求向 IAM `/internal/v1/auth/me` 取并集，**改权限后下一次请求立即生效** |
| 角色上下文 | 多角色用户必须带 `X-Role-Context`，单角色可省略；不匹配返回 403 并写安全审计（决策 D-03） |
| 越权审计 | 缺权限、令牌无效、角色上下文不符都写 `security_event`：`auth.permission.denied`、`auth.token.invalid`、`auth.role_context.denied`、`gateway.permission.denied` |
| 停用账号 | 每请求校验账号状态；停用后既有令牌立即失效，重新登录也被拒绝 |
| 退出 | `POST /api/v1/auth/logout` 为无状态退出（写审计 + 客户端丢弃令牌），令牌仍受 TTL 与状态检查约束 |

业务服务怎么接入（三行）：

```python
from nis_shared.auth import Principal, require_permission

@router.post("/records", status_code=201)
def create_record(
    payload: RecordWrite,
    principal: Principal = Depends(require_permission("recon:create")),
) -> dict:
    ...  # principal.user_id / role_context / permissions 可直接用
```

- 只要求登录、不要求具体权限时用 `Depends(get_principal)`；
- 资源范围（本人/被指派/组织）继续由业务接口判断，权限代码只是必要条件；
- 内部调用统一走 `nis_shared.clients`（连接 1 秒、总 3 秒，错误映射为稳定错误码）。

## 业务链（Issue #9 起可用）

侦察与分析两段已按契约打通，Gateway 负责注入身份、下游服务负责资源范围：

| 操作 | 入口 | 权限 | 资源范围 |
|---|---|---|---|
| 侦察记录列表/详情 | `GET /api/v1/recon-records[/{id}]` | `recon:read_assigned` | 本人创建 或 被指派 |
| 新建/编辑草稿 | `POST`、`PATCH /api/v1/recon-records[/{id}]` | `recon:create`、`recon:edit_own_draft` | 本人；仅 `draft` |
| 提交并指派分析员 | `POST /api/v1/recon-records/{id}/submit` | `recon:submit` | 本人；`Idempotency-Key` 重放返回原结果 |
| 分析报告列表/详情 | `GET /api/v1/analysis-reports[/{id}]` | `analysis:read_assigned` | 作者 或 被指派决策员 |
| 新建/编辑草稿 | `POST`、`PATCH /api/v1/analysis-reports[/{id}]` | `analysis:create`、`analysis:edit_own_draft` | 作者；引用侦察记录必须已指派给该作者 |
| 提交并指派决策员 | `POST /api/v1/analysis-reports/{id}/submit` | `analysis:submit` | 作者；`ai_content_confirmed=true` 才放行 |

要点：

- **身份只从令牌来**：`owner_id` / `author_id` / `viewer_user_id` 由 Gateway 注入，浏览器传了也不认；
- **侦察快照由服务端生成**：分析服务通过 `authorized-view?purpose=analysis` 取记录，写进 `report_recon_links` 的是不可变快照，不信任前端提交的内容；
- **越权不泄露存在性**：无权的记录/报告按 `404` 处理，同时写 `*.read` 的 `denied` 审计；
- **提交后不可改**：状态不是 `draft` 时 `PATCH` 返回 `409 WORKFLOW_CONFLICT`；版本不匹配返回 `409 VERSION_CONFLICT`；
- **多分析员并存**：同一侦察记录可以有多份报告，互不覆盖；记录级状态只有全部指派完成后才汇总为 `analyzed`。

## 决策与执行（Issue #10 起可用）

| 操作 | 入口 | 权限 | 关键规则 |
|---|---|---|---|
| 指令列表/详情/状态 | `GET /api/v1/commands[/{id}][/status]` | `command:read_assigned` | 本人创建 或 被指派执行员 |
| 新建/编辑草稿 | `POST`、`PATCH /api/v1/commands[/{id}]` | `command:create` | 依据报告必须已指派给本人 |
| 冲突检查 | `GET /api/v1/commands/conflicts` | `command:issue` | 同一依据报告或同一目标上的活动指令 |
| 下达 | `POST /api/v1/commands/{id}/issue` | `command:issue` | 有冲突必须 `conflict_acknowledged=true`，否则 409 |
| 取消 | `POST /api/v1/commands/{id}/cancel` | `command:issue` | 已有完成结果的不能取消 |
| 我的执行任务 | `GET /api/v1/assignments[/{id}]` | `command:read_assigned` | 只看自己的分配，他人分配返回 404 |
| 接收/拒绝/开始/完成 | `POST /api/v1/assignments/{id}/{accept,reject,start,complete}` | `execution:respond/update/submit` | 状态机校验 + 版本校验 |

**总体状态只有一个计算入口**（决策 D-01）：

- `commands.status` 只由 decision-service 的 `recompute_status()` 重算；
- 重算时机只有 `confirm-issue` 与每次 `assignment-state` 回写；
- execution-service 不计算、不保存总体状态；`GET /commands/{id}/summary` 的 `aggregate_status` 是从决策侧读来的；
- 每次重算写一条 `command.status.recalculated` 审计。

**下达是跨服务流程**（architecture §7）：决策服务校验执行员 → 调 Execution 建个人分配 → 回写本地摘要 → 状态汇总为 `issued`；Execution 不可用时指令落 `compensation_required`，不会显示为已下达。

## 审计与 AI（Issue #11 起可用）

**审计**（`audit-service`，8007）：

- 写入：`POST /internal/v1/audit-events`，只追加、按 `request_id + service + action + result` 幂等；
- 查询：`GET /api/v1/audit-events`，支持 `resource_type` / `resource_id` / `request_id` / `actor_user_id` / `result` / `from` / `to` + 分页，需要 `audit:read`；
- 调用链：`GET /api/v1/audit-events/traces/{request_id}`，返回该请求跨服务的全部事件（按事件号排序）、起止时间与最终结果；
- 范围：登录、失败登录、越权、角色上下文不符、创建/提交/指派/下达/回写/取消、AI 建议生成与处理；
- 不记录：密码、Token、完整敏感正文（`details` 只放业务标识与状态）；
- 账号权限：`nis_audit_app` 对 `audit_events` 只有 `SELECT`/`INSERT`，仅 `audit_trace_index` 可 `UPDATE`（派生索引）。

一次业务动作的跨服务调用链示例（同一条 `X-Request-ID`）：

```text
execution-service  execution_assignment.create  success  actor=decision_maker
decision-service   command.issue                success  actor=decision_maker
```

**AI 建议**（`ai-service`，8006）：

- 请求：`POST /api/v1/ai/suggestions`（`stage` + `business_object_type` + `business_object_id` + `suggestion_type`）；
- 处理：`POST /api/v1/ai/suggestions/{id}/decision`，`decision` 只能是 `accepted` / `edited`（必须带 `edited_content`）/ `rejected`；
- 人在回路：建议初始为 `pending`，只有人工处理后才有 `human_confirmed_by` / `human_confirmed_at`；重复处理返回 409；
- 可降级：`AI_ENABLED=false` 或模型不可用时返回 503 `SERVICE_UNAVAILABLE`，人工流程照常；
- 本期实现是**可复现的规则模板**（`model_name=nis-rule-based`），不依赖外部模型，替换模型时只改 `app/service.py` 的 `generate()`。

## 证据文件（决策 D-02）

| 操作 | 入口 | 权限 |
|---|---|---|
| 下载侦察证据 | `GET /api/v1/recon-records/{id}/evidence/{evidence_id}` | `recon:read_assigned` + 记录可见 |
| 下载执行证据 | `GET /api/v1/assignments/{id}/evidence/{evidence_id}` | `command:read_assigned` + 本人分配 |

- 文件本体在 `EVIDENCE_ROOT` 指向的受控目录，按 `<资源类型>/<资源 UUID>/<文件名>` 分目录；
- 数据库只存文件名、媒体类型、大小、`sha256`、`storage_ref`，**不存绝对路径**；
- 下载由业务服务鉴权后流式返回，Gateway 只做代理；每次下载写 `evidence.download` 审计（含 sha256）；
- 路径解析拒绝绝对路径与 `..`，越界一律 404；受控目录**不要**挂成公开静态路径；
- 备份范围必须包含该目录（`deploy/README.md`），但备份文件不进 Git。

## 本地启动（Issue #7 起可用）

共享库在 `services/_shared/nis_shared`（配置、数据库、错误体、健康检查、日志、密码哈希），
每个服务的 `app/main.py` 只有十行左右：加载配置 → 建数据源 → 装配应用。

```bash
# 0. 一次准备：虚拟环境与依赖
python -m venv .venv
.venv/Scripts/python -m pip install -r services/requirements.txt

# 1. 空库迁移（按数据模型第 12 节顺序：IAM → Audit → 四段业务 → AI）
python scripts/migrate_all.py --verify

# 2. 种子数据：5 个组织、18 个权限、5 个角色、8 个演示账号
set NIS_ADMIN_PASSWORD=...      # 只放本地环境变量
set NIS_DEMO_PASSWORD=...
python scripts/seed_data.py

# 3. 单独起某个服务（端口见 docs/service-catalog.md 第 1 节）
cd services/iam-service
set PYTHONPATH=..;..\_shared
python -m uvicorn app.main:app --port 8001
```

健康检查是契约的一部分，任何服务都应满足：

- `GET /health/live` → 200，进程存活即通过；
- `GET /health/ready` → 200 或 503，503 时使用统一错误体并给出 `dependencies`；
- 两者都回写 `X-Request-ID`，便于和审计事件对齐。

## 代码约定

- 业务代码分层：`app/api`（路由与参数校验）、`app/domain`（规则与状态转换）、
  `app/db`（模型与会话，目前是 `app/models.py`）、`app/clients`（跨服务客户端）；
- 共享库只放基础设施，**不放业务规则**；业务规则属于各自服务；
- 报错一律 `raise ApiError("WORKFLOW_CONFLICT", ...)`，不要手写 JSONResponse 拼错误体；
- 数据表字段名必须与 `docs/data-model.md` 一致，改名属于契约变更。

## 测试

```bash
python -m pytest tests -q
```

测试用内存 SQLite，不连开发者本机数据库；真实 MySQL 的迁移验证由
`python scripts/migrate_all.py --verify` 完成（证据见 PR）。

分层说明：

| 文件 | 覆盖 |
|---|---|
| `tests/test_contract_alignment.py` | **契约一致性**：不许发明路由、不许静默漏实现、错误体与健康检查符合契约 |
| `tests/test_health.py`、`test_models.py`、`test_seed.py` | 骨架、数据模型、种子 |
| `tests/test_auth.py`、`test_rbac*` | 认证、令牌、角色上下文、权限即时生效 |
| `tests/test_recon_analysis.py`、`test_decision_execution.py` | 四段业务链与状态机 |
| `tests/test_audit_trace.py`、`test_audit_ingest.py` | 审计写入/查询/调用链与 AI 建议 |
| `tests/test_gateway.py` | 网关转发、入口鉴权、错误体 |

新增或修改路由后，`test_contract_alignment.py` 会强制你二选一：改契约（走评审），
或把该路由登记进 `KNOWN_PENDING` / `KNOWN_EXTRA` 并写明原因。

