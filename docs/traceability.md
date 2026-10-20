# 需求追踪矩阵

状态说明：`未开始`、`设计中`、`实现中`、`待测试`、`通过`、`失败`。当前仅建立基线，不能把设计完成标记为功能通过。

| 验收项 | 需求 | 设计依据 | 主责 | 计划测试 | 当前状态 |
|---|---|---|---|---|---|
| TC-B01 中心数据库与数据存储 | FR-RECON-003、FR-ANALYSIS-004、FR-DECISION-003、FR-EXEC-002 | architecture §4 | B、D | 四环节提交后核对数据库 | 未开始 |
| TC-B02 日志完整性 | FR-AUDIT-001~003 | rbac §6、workflow §1 | B、D | 执行正常/失败操作并核对日志 | 未开始 |
| TC-B03 三个网络区域 | NFR-NET-001 | architecture §6、network-lab-plan | D | 查看三域网段和网关 | 设计中 |
| TC-B04 内网访问外网和 DMZ | NFR-NET-001 | architecture §6 | D | 内网 HTTP/连通测试 | 未开始 |
| TC-B05 外网访问 DMZ | NFR-NET-001 | architecture §6 | D | 外网访问映射服务 | 未开始 |
| TC-B07 DMZ 禁止访问内网 | NFR-SEC-002 | architecture §6 | D | DMZ 到内网端口拒绝及日志 | 未开始 |
| TC-B08 四角色认证 | FR-AUTH-001~002 | rbac §3、§5 | B、C | 四类账号单次登录 | 设计中 |
| TC-B09 RBAC 越权拦截 | FR-AUTH-005 | rbac §4~§7 | B、C | 页面、数据、API 越权矩阵 | 设计中 |
| TC-B10 用户/角色/权限分离 | FR-AUTH-003 | rbac §1 | B、C | 后台配置角色权限并验证继承 | 设计中 |
| TC-B11 多对多映射 | FR-AUTH-004 | rbac §1、§5 | B、C | 多用户同角色、多角色用户 | 设计中 |
| TC-B12 完整 OODA | FR-RECON-*、FR-ANALYSIS-*、FR-DECISION-*、FR-EXEC-* | workflow、architecture §5 | 全员 | 四账号完整闭环及入库 | 设计中 |
| TC-B13 AI + 人在回路 | FR-RECON-002、FR-ANALYSIS-003、FR-DECISION-002、FR-EXEC-003、NFR-AI-001 | workflow §7 | A、B、C | 四环节建议、确认、降级 | 设计中 |
| TC-B14 多角色多用户调度 | FR-AUTH-004、FR-ORG-002 | rbac §4~§5 | A、B、C | 同角色多账号选择与并行流转 | 设计中 |
| TC-B15 组织候选筛选 | FR-ORG-001~002 | rbac §4 | A、B、C | 组织匹配/不匹配候选列表 | 设计中 |
| TC-SOA01 Gateway 唯一入口 | NFR-SOA-001 | architecture §11、soa-deployment | B、D | 外网只能访问 Gateway，内部端口拒绝 | 设计中 |
| TC-SOA02 服务契约与边界 | NFR-SOA-002 | service-catalog、service-contracts | A、B | OpenAPI 与契约测试 | 设计中 |
| TC-SOA03 Schema 数据所有权 | NFR-SOA-003 | data-ownership | B、D | 数据库账号跨 Schema 写入拒绝 | 设计中 |
| TC-SOA04 请求追踪与幂等 | NFR-SOA-004 | service-contracts、workflow | A、B | 重复提交和跨服务失败测试 | 设计中 |
| TC-SOA05 独立健康检查与部署 | NFR-SOA-005 | service-catalog、soa-deployment | B、D | Compose、健康检查与单服务故障测试 | 设计中 |
| TC-E01 数据安全 | NFR-SEC-001~003、FR-BACKUP-001 | architecture §6~§7 | B、D | 哈希、访问限制、备份恢复 | 设计中 |
| TC-E02 软件工程管理 | NFR-MAINT-001 | CONTRIBUTING、任务清单 | A、全员 | 仓库、PR、文档和追踪记录 | 实现中 |
| TC-E03 优先级 | FR-PRIORITY-001 | requirements §3.6 | B、C | 普通/紧急保存、排序和展示 | 设计中 |
| TC-D01 契约与数据模型一致性 | NFR-SOA-002、NFR-SOA-003 | contracts/、api-catalog、data-model | A | `python scripts/validate_contracts.py` 通过，且契约字段与数据模型逐列核对 | 设计中 |
| TC-D02 演示数据与四角色账号 | FR-AUTH-001、FR-ORG-001 | demo-script、scripts/seed_demo_data.py | A | 空库执行种子脚本后四类账号可登录并各完成一步业务 | 设计中 |

## 证据规则

- 测试通过后填写关联 Issue/PR、构建提交号和 `evidence/` 路径。
- 测试证据必须对应实际团队环境，不复制课程示例结果。
- 实测失败保留记录并建立缺陷 Issue，修复复测后追加结果，不覆盖历史。
- 中期验收前由 A、D 共同核对全部 P0 行均有真实测试结果。
