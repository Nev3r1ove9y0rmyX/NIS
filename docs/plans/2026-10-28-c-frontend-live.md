# C 第二批实施计划：前端接入真实接口

**日期**：2026-10-28
**Goal**：把第一批的界面原型升级为**真实可演示**的四角色系统：真实登录、真实业务链、真实审计，
并交付 C-09 的联调证据与 C-10 的用户手册。

**Architecture**：浏览器只与 Gateway 同源通信（开发 Vite 反代 / 部署 nginx 反代）；
类型由契约生成；四个工作台各自一个业务面板组件，提交类动作统一走幂等键 + `expected_version`。

**Tech Stack**：Vue 3、Vite、TypeScript、Vue Router、Vitest、Playwright（验收）。

## 依据

- A：`contracts/openapi/api-gateway.yaml`（基线 1.0）、`docs/rbac.md`、`docs/workflow.md`、`docs/api-catalog.md`、`docs/demo-script.md`、`frontend/README.md` 的 5 条规则。
- B：`services/`（8 个服务）+ `services/STATUS.md` 的交付状态与已知限制。
- D：`deploy/`（Compose、nginx 同源反代、备份与基线脚本）。

## 第一批与第二批的差别

| 项 | 第一批（已完成） | 第二批（本次） |
|---|---|---|
| 数据来源 | 内存虚构原型，明确标注不上后端 | 真实 `/api/v1`，无 mock |
| 认证 | 适配层默认关闭 | 真实登录 + 多角色工作台 + 401/403 处理 |
| 类型 | 手写占位 | `openapi-typescript` 从契约生成 |
| 业务 | 只验证交互 | 侦察/分析/决策/执行四段闭环 |
| AI | 未接入占位 | 请求 → 接受/修改/舍弃 → 人工确认 |
| 证据 | 只记文件名 | 浏览器算 sha256 提交元数据，下载失败如实提示 |
| 审计 | 页面内内存事件 | 真实 `audit:read` 查询 + 调用链还原 |

## 文件组织

```text
frontend/
  src/
    api/          client.ts（请求/错误/幂等）、endpoints.ts（按 operationId）、types.ts（别名+标签）、schema.d.ts（生成）
    components/   AppShell、AppDialog、ConfirmDialog、DataState、StatusPill、ToastHost、
                  CandidatePicker（服务端候选）、EvidencePicker（sha256）、AiSuggestionPanel
    composables/  usePagedList（加载/失败/空/分页一致）
    features/     recon/ReconPanel、analysis/ReportPanel、decision/CommandPanel、execution/AssignmentPanel
    stores/       session（Token/角色上下文/权限）、toast
    views/        LoginView、四个工作台、AuditView、MessageView
  tests/          （已并入 src/__tests__，vitest 直接跑）
scripts/dev_stack.py      本地 SQLite 全栈启动器（C 新增，开发用）
tests/ui/e2e_four_roles.py 四角色浏览器验收（C 新增）
docs/user-guide.md         真实系统用户手册（C-10）
docs/frontend-integration.md  联调清单与缺口上报（G1–G6）
```

## 顺序与验证点

1. 跑通后端基座：`pytest tests -q`（129 passed）、`dev_stack.py init/run`、`status` 全绿。
2. 生成类型并重写请求层，先做登录 + 角色路由；用真实账号验证四个工作台入口与 403 页面。
3. 逐域接业务：侦察 → 分析 → 决策 → 执行，每段完成后用探针脚本核对返回字段与状态流。
4. 补 C-08 体验：加载/防重复/409 双语义/422 字段回显/分页筛选/键盘可达。
5. `npm run check`（lint + typecheck + 22 项测试 + build）→ 浏览器 31 步端到端验收 → 截图落盘。
6. 写 C-10 用户手册与联调清单，把发现的 6 个缺口按负责人分派。

## 不做 / 移交

- 不改 B 的服务业务逻辑；唯一例外是 G1（退出接口 204 带响应体）已修并标注请 B 复核。
- 不新造接口：证据上传端点缺失就走“元数据 + 如实提示”，等 A/B 决策（G2）。
- 不接 Docker：本机 daemon 不可用，正式部署仍以 D 的 Compose 为准。
