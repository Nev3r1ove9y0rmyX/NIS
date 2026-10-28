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

## 接口与数据基线

- [契约目录说明](contracts/README.md)
- [公共 API 契约（OpenAPI 3.1）](contracts/openapi/api-gateway.yaml)
- [共享枚举与错误组件](contracts/schemas/common.yaml)
- [接口清单（含权限与幂等要求）](docs/api-catalog.md)
- [数据模型与 ER 图](docs/data-model.md)
- [接口与数据模型评审记录](docs/reviews/interface-review.md)
- [固定演示数据与演示脚本](docs/demo-script.md)

契约校验：

```bash
python scripts/validate_contracts.py
```

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

## 目录约定

| 目录 | 内容 | 主责 | 入口 |
|---|---|---|---|
| `frontend/` | Vue 3 前端工程与四类角色工作台 | C | [说明](frontend/README.md) |
| `services/` | Gateway 与 7 个业务服务 | B | [说明](services/README.md) |
| `contracts/` | OpenAPI 契约与共享枚举、错误码 | A | [说明](contracts/README.md) |
| `deploy/` | 容器编排、反代、MySQL 与备份脚本 | D | [说明](deploy/README.md) |
| `docs/` | 需求、设计、接口、任务与手册 | A | [设计基线](#设计基线) |
| `tests/` | 契约、接口、端到端与网络测试 | 全员 | [说明](tests/README.md) |
| `evidence/` | 验收截图与脱敏日志 | A | [说明](evidence/README.md) |
| `scripts/` | 契约校验、演示数据、GitHub 同步 | A | [说明](#常用命令) |

## 常用命令

```bash
# 校验 OpenAPI 契约（重复键、结构、引用、枚举）
python scripts/validate_contracts.py

# 校验文档相对链接
python scripts/check_doc_links.py

# 同步 GitHub 标签、里程碑、Issue（幂等，令牌取自 Git 凭据管理器）
powershell -File scripts/bootstrap-github.ps1 -DryRun
powershell -File scripts/bootstrap-github.ps1
```

## 前端与联调（成员 C）

前端已从“内存原型”升级为**连接真实接口**的版本：Vue 3 + Vite + TypeScript，类型由
[公共 API 契约](contracts/openapi/api-gateway.yaml) 生成，浏览器只与 Gateway 同源通信。

- 用户操作说明（四角色、常见错误、演示脚本）：[docs/user-guide.md](docs/user-guide.md)
- 联调清单、实现约定与待确认缺口（G1–G6）：[docs/frontend-integration.md](docs/frontend-integration.md)
- 验证记录与截图索引：[evidence/frontend-c-validation.md](evidence/frontend-c-validation.md)

```powershell
# 1) 后端栈（需 B 的服务分支已合并到本分支后才能用）
#    本机不想开 Docker 时用开发启动器：SQLite 建表 + 种子 + 起 8 个进程，不改任何服务代码
python -m venv .venv; .\.venv\Scripts\python -m pip install -r services/requirements.txt
python scripts/dev_stack.py init      # 建表 + IAM 种子（需先在 .env 设 NIS_ADMIN_PASSWORD/NIS_DEMO_PASSWORD）
python scripts/dev_stack.py run       # 起 8 个服务
python scripts/dev_stack.py status    # 逐个 /health/ready

# 2) 前端（可独立运行与检查）
cd frontend
npm install
Copy-Item .env.example .env           # VITE_API_BASE_URL=/api/v1，Vite 反代到 Gateway
npm run dev

# 3) 检查与验收
npm run check                          # lint + 类型 + 22 项测试 + 构建
npm run generate:api                   # 契约变更后重新生成类型
python tests/ui/e2e_four_roles.py      # 四角色真实链路验收，产出 evidence/screenshots（需后端栈已起）
```

正式部署仍按 [deploy/README.md](deploy/README.md) 用 Docker Compose + MySQL；前端同源反代由
`deploy/nginx/conf.d/nis.conf` 承担，所以后端不需要开 CORS。

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
