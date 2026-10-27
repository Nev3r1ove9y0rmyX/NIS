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

