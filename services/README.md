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
