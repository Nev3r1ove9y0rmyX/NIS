# SOA 服务契约规范

版本：0.1

## 1. 版本与路径

- 浏览器到 Gateway：`/api/v1/...`
- Gateway/服务到内部服务：`/internal/v1/...`
- 破坏兼容性的变更必须升级主版本或经过全组迁移评审。
- OpenAPI 文件存放于 `contracts/openapi/{service}.yaml`。

## 2. 通用请求头

| Header | 来源 | 用途 |
|---|---|---|
| `Authorization: Bearer ...` | 客户端/IAM | 用户身份；内部服务必须验证 |
| `X-Request-ID` | Gateway | 全调用链追踪 UUID |
| `X-Role-Context` | 客户端经 Gateway | 用户当前操作角色，必须属于 JWT 中有效角色 |
| `Idempotency-Key` | 客户端/Gateway | 关键创建和提交操作去重 |
| `X-Service-Name` | 内部服务 | 服务身份辅助审计，不单独作为信任依据 |

## 3. 通用错误格式

```json
{
  "code": "WORKFLOW_CONFLICT",
  "message": "当前状态不允许该操作",
  "request_id": "uuid",
  "details": {}
}
```

稳定错误码至少包括：

| HTTP | 错误码 | 含义 |
|---:|---|---|
| 400 | `INVALID_REQUEST` | 请求结构或业务参数错误 |
| 401 | `UNAUTHENTICATED` | 未登录、Token 无效或过期 |
| 403 | `FORBIDDEN` | 已认证但无权限或资源范围不符 |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在或按防泄露规则不可见 |
| 409 | `VERSION_CONFLICT` | 乐观锁版本冲突 |
| 409 | `WORKFLOW_CONFLICT` | 非法状态转换 |
| 409 | `DUPLICATE_OPERATION` | 重复且无法安全返回原结果 |
| 422 | `VALIDATION_ERROR` | 字段校验错误 |
| 502 | `DEPENDENCY_FAILURE` | 下游服务失败 |
| 503 | `SERVICE_UNAVAILABLE` | 服务未就绪或暂不可用 |
| 504 | `DEPENDENCY_TIMEOUT` | 下游服务超时 |

## 4. 超时与重试

- 默认内部连接超时 1 秒、总请求超时 3 秒；AI 请求可单独配置为 15 秒。
- 查询类 GET 最多重试 1 次，带指数退避和随机抖动。
- 写操作只有在提供幂等键且契约明确支持时才能重试。
- 禁止无限重试；超时必须保留相同 `X-Request-ID`。
- 实际数值可通过环境变量调整，但测试和报告必须记录配置。

## 5. 幂等规则

下列操作必须支持 `Idempotency-Key`：

- 提交侦察记录；
- 提交分析报告；
- 下达指令；
- 创建执行分配；
- 提交执行结果；
- 关键审计事件写入。

同一用户、同一端点、同一幂等键和等价请求返回原结果；请求体不同则返回 `409 IDEMPOTENCY_CONFLICT`。

## 6. 分页、时间和标识符

- 列表使用 `page`、`page_size`，`page_size` 默认 20、最大 100。
- 响应包含 `items`、`page`、`page_size`、`total`。
- 跨服务标识符统一使用 UUID 字符串。
- 时间传输使用 ISO 8601 UTC，例如 `2026-10-16T08:30:00Z`。
- 数据库可保存 UTC；界面按用户环境显示。

## 7. 身份和服务信任

- Gateway 与业务服务都验证用户 JWT；服务不能只信任 Gateway 传入的用户头。
- IAM 私钥不得共享；业务服务使用 IAM 公钥验证。
- 内部服务仅在受控容器网络可访问。
- P0 阶段服务间认证可使用受控网络加服务令牌；服务令牌从环境变量/Secret 注入，不写入仓库。
- 用户上下文和服务身份必须分别记录，禁止用服务账号替代最终操作者审计。

## 8. 契约变更流程

1. 在 `contracts/openapi` 修改契约候选；
2. 标注兼容或破坏性变更；
3. B 检查服务实现，C 检查前端，D 检查部署，A 批准；
4. 更新契约测试和文档；
5. 合并后按依赖顺序发布。

禁止先修改服务返回结构、再让其他成员被动适配。
