# NIS 协同调度信息系统

本项目用于完成“网络信息系统解构”课程中的协同调度信息系统设计、实现、网络部署、安全加固与演练任务。

系统围绕 OODA 思路实现一条完整协同链：

```text
侦察员提交侦察数据
  -> 分析员形成分析报告
  -> 决策员下达行动指令
  -> 执行员反馈执行结果
  -> 全过程进入审计日志
```

## 团队分工

| 成员 | 开发主责 | 演练角色 | 任务入口 |
|---|---|---|---|
| A | 产品、需求、架构、集成、文档 | 决策员 | [A 任务书](docs/tasks/A.md) / [A 提示词](docs/prompts/A.md) |
| B | 后端、数据库、认证授权、审计 | 分析员 | [B 任务书](docs/tasks/B.md) / [B 提示词](docs/prompts/B.md) |
| C | 前端、交互、四角色工作台 | 侦察员 | [C 任务书](docs/tasks/C.md) / [C 提示词](docs/prompts/C.md) |
| D | 网络、部署、安全、测试 | 执行员 | [D 任务书](docs/tasks/D.md) / [D 提示词](docs/prompts/D.md) |

完整安排见 [项目开发任务清单](项目开发任务清单.md) 和 [GitHub 协作规范](CONTRIBUTING.md)。

四台电脑的联调与验收网络见 [组网与部署建议](docs/network-lab-plan.md)。

## 设计基线

- [课程要求核对表](docs/course-requirements-checklist.md)
- [需求规格说明书](docs/requirements.md)
- [角色与权限设计](docs/rbac.md)
- [业务状态机](docs/workflow.md)
- [系统总体架构](docs/architecture.md)
- [SOA 服务目录](docs/service-catalog.md)
- [服务契约规范](docs/service-contracts.md)
- [数据所有权](docs/data-ownership.md)
- [SOA 部署设计](docs/soa-deployment.md)
- [需求追踪矩阵](docs/traceability.md)
- [Sprint 01 任务卡](docs/sprint-01.md)

## 已审核技术架构

- 前端：Vue 3、Vite、TypeScript
- 架构：课程适配型 SOA、单仓库、统一 API Gateway
- 服务：FastAPI、SQLAlchemy、Pydantic，8 个粗粒度服务
- 通信：REST/JSON、OpenAPI，同步调用为主
- 数据库：一个 MySQL 8 实例，按服务划分逻辑 Schema
- 部署：Docker Compose、Ubuntu 虚拟机
- 认证授权：JWT、RBAC
- 网络：外部网络、DMZ、信任内网三个区域

消息队列、服务注册中心和分布式事务不属于 P0 依赖。架构变更必须形成 Architecture Decision Record，并确保功能、接口、网络和验收要求保持不变。

## 目标目录

```text
frontend/             前端工程
services/             Gateway 与 SOA 服务
contracts/            OpenAPI、共享 Schema 和错误码契约
deploy/               容器、服务器和网络部署文件
docs/                 需求、设计、接口、任务与手册
tests/                 接口、端到端与网络测试
evidence/              验收截图和脱敏日志
scripts/               初始化、备份和辅助脚本
```

## 第一阶段完成标准

1. 四类角色能够登录，并受到前后端双重权限控制。
2. 可以完整演示侦察、分析、决策、执行闭环。
3. 中心数据库保存关键业务数据。
4. 所有关键操作都有可查询的审计日志。
5. 多用户可从不同终端同时使用系统。
6. 系统部署在包含信任内网和 DMZ 的网络中。
7. 外部网络只可访问明确公开的端口，DMZ 默认不能访问内网核心资源。

## 资料合规

课程原始 PDF、DOCX、教师模板及其他标注“严禁外传”的材料不得提交到本仓库。仓库只保存团队原创代码、设计文档和经过脱敏的测试证据。
