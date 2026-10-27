# SOA 数据所有权

版本：1.0（已冻结，2026-10-27）

## 1. 中心数据库结构

项目使用一个 MySQL 8 实例。逻辑 Schema 与服务一一对应：

| Schema | 所属服务 | 主要数据 |
|---|---|---|
| `nis_iam` | IAM & Organization | 用户、角色、权限、组织、关联关系 |
| `nis_recon` | Reconnaissance | 侦察记录、分析员指派、证据元数据 |
| `nis_analysis` | Analysis | 分析报告、侦察引用、决策员指派 |
| `nis_decision` | Decision | 指令、冲突检查、整体状态摘要 |
| `nis_execution` | Execution | 个人分配、执行状态、结果 |
| `nis_ai` | AI Assistance | AI 请求、建议、模型及人工处理元数据 |
| `nis_audit` | Audit | 操作事件、系统事件、调用链索引 |

Gateway 不拥有 Schema。

## 2. 所有权规则

1. 每个服务使用独立数据库账号，只获得自己 Schema 的必要权限。
2. 服务不得对其他 Schema 执行 `INSERT`、`UPDATE`、`DELETE`。
3. 跨服务数据通过 REST API 获取，不通过跨 Schema JOIN 构建业务逻辑。
4. 跨服务引用使用 UUID，并可保存提交时的必要不可变快照，例如标题和作者显示名。
5. 不建立跨 Schema 外键；引用有效性由服务接口与契约测试保证。
6. 各服务独立维护 Alembic 迁移目录和版本表。
7. 数据导出、备份和恢复由 D 统一执行，但数据解释和迁移由所属服务负责。

## 3. 跨服务引用

| 所属服务 | 引用 | 校验方式 |
|---|---|---|
| Recon | 分析员用户 UUID | 提交时调用 IAM 候选接口 |
| Analysis | 侦察记录 UUID | 创建/读取时调用 Recon 授权接口 |
| Analysis | 决策员用户 UUID | 提交时调用 IAM 候选接口 |
| Decision | 分析报告 UUID | 创建时调用 Analysis 授权接口 |
| Decision | 执行员用户 UUID | 下达时调用 IAM 候选接口 |
| Execution | 指令 UUID | 创建分配时验证 Decision 的内部请求 |
| AI | 业务对象 UUID | 只作来源引用，不读取其他 Schema |
| Audit | 业务对象 UUID | 用于追踪，不作为业务真相来源 |

## 4. 数据一致性

- 服务内使用 ACID 本地事务。
- 跨服务写操作通过幂等接口和状态机实现最终一致。
- 上游资源删除采用停用、归档或软删除，避免悬空引用。
- 业务显示需要的不可变信息可以保存快照；实时状态必须从所有者服务获取。
- 数据冲突或引用失效写入审计，并进入补偿流程。

## 5. 备份恢复

- 中心实例整体备份，确保多个 Schema 位于一致恢复点。
- 恢复测试核对全部 Schema、账号权限和迁移版本。
- 恢复后执行跨服务引用完整性检查。
- 备份不得进入 Git；报告只保存脱敏命令、校验摘要和结果。
