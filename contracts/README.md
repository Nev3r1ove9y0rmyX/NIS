# 契约目录（contracts）

本目录是前后端联调的唯一接口基线。所有服务实现、页面字段和测试用例都必须用这里的
名字；任何改名都要走评审，不允许“先改代码再让别人适配”。

## 目录结构

```text
contracts/
  schemas/
    common.yaml            共享枚举、错误体、分页、通用头与审计字段
  openapi/
    api-gateway.yaml       浏览器唯一入口的公共契约（/api/v1）
    iam-service.yaml       内部契约：认证、用户、角色、权限、组织、候选
    recon-service.yaml     内部契约：侦察记录、指派、证据
    analysis-service.yaml  内部契约：分析报告、引用、决策员指派
    decision-service.yaml  内部契约：指令、冲突检查、总体状态
    execution-service.yaml 内部契约：个人分配、执行结果
    ai-service.yaml        内部契约：四环节统一建议与人工确认
    audit-service.yaml     内部契约：审计事件与调用链
```

- 公共契约以 `/api/v1` 为前缀，浏览器只访问这一层；
- 内部契约以 `/internal/v1` 为前缀，只在 DMZ 容器网络内可达，不做端口映射；
- `common.yaml` 不是完整 OpenAPI 文档，只提供被其他文件以外部引用复用的组件。

## 引用方式

```yaml
# 引用共享组件（相对于当前文件）
$ref: '../schemas/common.yaml#/components/schemas/Error'

# 引用同一文件内的组件
$ref: '#/components/schemas/ReconRecord'
```

不要在多个文件里复制同一份枚举定义；枚举只允许在 `common.yaml` 出现一次。

## 校验

```bash
python scripts/validate_contracts.py
```

脚本会检查：

1. YAML 能解析且**没有重复键**（重复键会被静默覆盖，是契约最常见的隐蔽错误）；
2. 顶层字段完整，`openapi` 为 3.1.x；
3. 每个操作有唯一 `operationId`、有成功响应、使用的标签已声明；
4. 路径模板里的 `{参数}` 都有对应的 `parameters` 声明；
5. 所有 `$ref`（含跨文件）都能解析到目标；
6. 使用 `security` 的文件必须声明对应的 `securitySchemes`；
7. 共享枚举非空、无重复值。

提交前必须校验通过；CI 接入后作为必过检查。

## 与文档的关系

| 文档 | 作用 |
|---|---|
| [api-catalog.md](../docs/api-catalog.md) | 人读接口清单，含权限和幂等要求 |
| [data-model.md](../docs/data-model.md) | 接口字段到数据库字段的对照 |
| [service-contracts.md](../docs/service-contracts.md) | 请求头、错误码、超时、幂等和变更流程 |
| [workflow.md](../docs/workflow.md) | 状态枚举与允许的状态转换 |
| [rbac.md](../docs/rbac.md) | 权限代码与资源范围规则 |

契约、清单、数据模型和状态机四者必须一致；发现不一致时先建立 Issue，再同步修改，
不能只改其中一处。
