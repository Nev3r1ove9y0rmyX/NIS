# 接口与数据模型评审记录（A-05）

版本：1.0（已冻结，2026-10-27）

主持人：A

冻结依据：[基线评审 30 分钟](baseline-review.md)第 4 节的 6 个决策（D-01 至 D-06），
全部采用推荐方案；冻结后按本文件第 6 节的规则变更。

评审对象：
[api-gateway.yaml](../../contracts/openapi/api-gateway.yaml)、
`contracts/openapi/*-service.yaml`、[common.yaml](../../contracts/schemas/common.yaml)、
[data-model.md](../data-model.md)、[api-catalog.md](../api-catalog.md)、
[workflow.md](../workflow.md)、[rbac.md](../rbac.md)。

评审目的：在 B 开始写服务、C 开始写页面前，把字段名、状态枚举、权限代码、错误码、
幂等与并发规则固定下来，形成可冻结的基线。

## 1. 评审规则

1. 逐条检查，不允许“看起来没问题”直接通过；每条结论必须能被验证。
2. 破坏兼容性的意见不直接改基线，先记为遗留问题，再决定是否建立变更 Issue。
3. 主持人（A）不代替 B/C/D 的判断；B 负责数据与接口可实现性，C 负责页面状态可实现性，
   D 负责部署与网络一致性。
4. 评审通过后冻结；冻结之后的每次修改都要更新本记录。

## 2. 检查表

图例：`✔` 主持人已核对通过；`待确认` 需要对应成员确认；`遗留` 已登记为遗留问题。

| # | 检查项 | 结论 | 依据 / 说明 | 确认人 |
|---:|---|:---:|---|---|
| 1 | 四类角色代码在契约、RBAC、数据模型中一致 | ✔ | `reconnaissance`/`analyst`/`decision_maker`/`executor` | A |
| 2 | 权限代码与 RBAC 第 2 节逐条对应 | ✔ | 18 个权限代码，无契约额外发明的权限 | A |
| 3 | 每个受保护接口都标注了所需权限 | ✔ | 见 [api-catalog.md](../api-catalog.md) 第 2 节 | A |
| 4 | 侦察记录状态枚举与状态机完全一致 | ✔ | `ReconStatus` 与 workflow 第 2 节一致 | A、B |
| 5 | 分析报告状态枚举与状态机完全一致 | ✔ | `ReportStatus` 与 workflow 第 3 节一致 | A、B |
| 6 | 指令总体状态可由个人分配状态汇总 | ✔ | 决策 D-01：只在 decision-service 重算，见 workflow 第 5.1 节 | B |
| 7 | 个人分配状态与指令总体状态不重复定义 | ✔ | 分配在 Execution，汇总在 Decision，通过 `assignment-state` 回写 | A、B |
| 8 | 状态转换只由后端校验，前端不得直接构造越权请求 | ✔ | workflow 第 1 节 | A、C |
| 9 | 关键提交接口均要求 `Idempotency-Key` | ✔ | 侦察提交、报告提交、下达、结果上报、创建 | A、B |
| 10 | 幂等键冲突（同键不同体）有稳定错误码 | ✔ | `IDEMPOTENCY_CONFLICT` 已加入服务契约第 3 节 | A |
| 11 | 可编辑资源都带 `expected_version` | ✔ | 提交类接口要求，旧版本返回 `VERSION_CONFLICT` | A、B |
| 12 | 分页参数与响应结构统一 | ✔ | `page`/`page_size`/`total`，上限 100 | A、C |
| 13 | 时间格式统一为 ISO 8601 UTC | ✔ | `Timestamp` 组件；数据库 `DATETIME(3)` | A、B |
| 14 | 跨服务标识统一 UUID，不暴露自增主键 | ✔ | 仅审计表对外用字符串事件号 | A、B |
| 15 | 错误体结构统一且不泄露内部信息 | ✔ | `{code, message, request_id, details}` | A、B |
| 16 | 错误码表覆盖契约中出现的全部状态码 | ✔ | 决策 D-04：保留 `423 ACCOUNT_LOCKED` 与 `429 RATE_LIMITED`，B 必须真实返回 | B |
| 17 | 请求头集合固定且用途明确 | ✔ | `Authorization`、`X-Request-ID`、`X-Role-Context`、`Idempotency-Key`、`X-Service-Name` | A |
| 18 | Gateway 不被当作唯一授权点 | ✔ | 架构第 10 节、服务契约第 7 节 | A、B |
| 19 | 每个服务只写自己的 Schema | ✔ | 数据所有权第 2 节、数据模型第 1.4 节 | A、B、D |
| 20 | 跨服务引用不建外键，改用 UUID + 快照 | ✔ | 数据模型第 1.4 节 | A、B |
| 21 | 快照字段命名带 `_snapshot` 后缀 | ✔ | `recon_title_snapshot`、`command_title_snapshot` 等 | A、B |
| 22 | 候选接收人筛选口径在服务端固定 | ✔ | 数据模型第 11 节；必要时提交时二次校验 `users/resolve` | A、B |
| 23 | AI 建议不能直接驱动状态转换 | ✔ | AI 服务只返回建议；确认后由业务接口提交 | A、B、C |
| 24 | AI 内容进入业务字段前有确认标志 | ✔ | `human_confirmed`、`ai_content_confirmed`、`human_confirmed_by/at` | A、B |
| 25 | AI 不可用时人工流程仍可继续 | ✔ | AI 契约降级说明；NFR-AI-001 | A、B、C |
| 26 | 审计事件字段可还原全过程 | ✔ | `request_id`、`actor_*`、`action`、`resource_*`、`result` | A、B |
| 27 | 审计表只追加，业务账号无 UPDATE/DELETE | ✔ | 数据模型第 10 节 | A、B、D |
| 28 | 审计不记录密码、Token、完整敏感正文 | ✔ | 字段说明与 `payload_digest` 设计 | A、B |
| 29 | 数据库不对外映射，仅 API 主机可连 | ✔ | 架构第 11 节、部署设计第 7 节 | A、D |
| 30 | 每个服务有 `/health/live` 与 `/health/ready` | ✔ | 服务目录第 10 节；所有契约均含两接口 | A、D |
| 31 | 契约中的路径与接口清单一致 | ✔ | 50 个操作，由 `scripts/validate_contracts.py` 交叉校验 | A |
| 32 | YAML 无重复键、引用全部可解析 | ✔ | 校验脚本通过（101 条路径 / 125 个操作 / 21 个共享组件） | A |
| 33 | 枚举只在 `common.yaml` 定义一次 | ✔ | 其他契约使用外部引用，不复制 | A、B |
| 34 | 数据模型字段与契约字段同名 | ✔ | 已逐表逐列核对；实现时如需调整类型长度，按变更流程记录，不改字段名 | B |
| 35 | 索引能支撑列表页查询模式 | ✔ | 按 `(owner/executor, status, updated_at)` 建复合索引，迁移文件中说明依据 | B |
| 36 | 迁移顺序与初始化顺序明确 | ✔ | 数据模型第 12 节：IAM → Audit → 业务服务 → AI → 种子 | B、D |
| 37 | 演示数据可重复生成且幂等 | ✔ | `seed_demo_data.py` 按 username/code 判重 | A |
| 38 | 演示密码不进入仓库 | ✔ | 由环境变量注入，仓库只有 `.env.example` | A、全员 |
| 39 | 服务间超时与重试有明确上限 | ✔ | 服务契约第 4 节：连接 1s / 总 3s / AI 15s | A、B |
| 40 | 部署结构与本契约的端口一致 | ✔ | 8000 至 8007 与 Compose 服务名已在 deploy/README.md 与 soa-deployment.md 对齐 | D |

## 3. 已完成的设计侧结论

1. 公共接口统一以 `/api/v1` 为前缀，健康检查在根路径；内部接口以 `/internal/v1` 为前缀，
   不对外暴露。
2. 侦察、分析、决策、执行四个环节各自拥有资源与状态，跨环节只通过 UUID 引用与快照，
   不做跨 Schema JOIN。
3. AI 在四个环节使用同一套“请求建议 → 人工处理 → 人工提交”流程，建议本身不改变状态。
4. 指令的“总体状态”与“个人分配状态”分离：Execution 拥有个人状态，Decision 保存摘要并按
   固定规则汇总，避免两处状态互相打架。
5. 候选接收人由 IAM 统一筛选，提交时再用 `users/resolve` 二次校验，防止前端伪造接收人。
6. 契约以 YAML + 共享组件库维护，`scripts/validate_contracts.py` 作为唯一机器校验手段。

## 4. 遗留问题

6 项均已由 [基线评审](baseline-review.md) 的决策关闭，冻结时无未决项。

| 编号 | 问题 | 影响 | 责任人 | 结论 | 状态 |
|---|---|---|---|---|---|
| R-01 | `command_assignments` 的汇总状态由谁重算、何时重算 | 可能出现指令状态与个人状态不一致 | B | 决策 D-01：只在 decision-service 重算，见 workflow 第 5.1 节 | 已解决 |
| R-02 | 证据文件的实际存储与下载鉴权 | 影响证据上传与验收演示 | B、D | 决策 D-02：受控目录 + Gateway 代理下载 + 下载审计 | 已解决 |
| R-03 | 429 限流与 423 锁定是否真的实现 | 影响错误码表完整性 | B | 决策 D-04：保留并必须真实返回，阈值可配 | 已解决 |
| R-04 | 多组织兼任是否需要 | 影响 `organization_memberships` 取舍 | A、B | 决策 D-05：一人一个主组织，本轮不做 | 已解决 |
| R-05 | `X-Role-Context` 是否强制 | 影响多角色用户的操作归属审计 | A、B、C | 决策 D-03：多角色必填，单角色可省略 | 已解决 |
| R-06 | 数据库账号与 Schema 授权的具体清单 | 影响部署与安全测试 | B、D | 决策 D-06：矩阵见 data-model 第 12.1 节 | 已解决 |

## 5. 基线冻结条件

同时满足以下条件后才把版本从 0.1 提升为 1.0 并宣布冻结（已于 2026-10-27 全部满足）：

- [x] 检查表中所有“待确认”项有明确结论（6 项决策 + 逐列核对）；
- [x] 遗留问题 R-01 至 R-06 已全部解决；
- [x] `python scripts/validate_contracts.py` 通过；
- [x] B 能据此提交 ER 与首批 API 实现，C 能据此写出四类工作台页面状态；
- [x] D 确认端口、环境变量与三域网络方案一致。

冻结后任何破坏兼容性的修改都必须建立变更 Issue，并在本记录追加一条变更说明。

## 6. 冻结后的变更记录

| 日期 | 版本 | 变更内容 | 关联 Issue | 批准 |
|---|---|---|---|---|
| 2026-10-27 | 1.0 | 首次冻结：D-01 至 D-06 落地；新增证据文件下载接口；`X-Role-Context` 多角色必填；补 `423 ACCOUNT_LOCKED` | #6 | A |
