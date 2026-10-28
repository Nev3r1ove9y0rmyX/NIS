# C 前端第一批实施计划

**Goal:** 交付 C-01 工程、C-02 可交互原型，以及 C-03 认证/权限基础，供 A/B 评审接入。

**Architecture:** Vue 3 + TypeScript + Vue Router；轻量共享认证状态；fetch 客户端集中处理 Token、超时和错误。原型使用独立内存数据，不能访问真实资源；真实认证适配器必须显式启用待评审契约。

**Tech Stack:** Vue 3、Vite、TypeScript、Vitest、ESLint、Playwright（浏览器验证）。

## 范围与依据

- 已阅读 README、CONTRIBUTING、C 任务书/提示词、B 任务书和项目任务清单。
- 本地只读提取父目录实验指导书、中期验收说明及模板；不复制原始材料到 Git。导论 PDF 未找到。
- 特别覆盖多角色账号（roles 数组而非单一 role）、人在回路、多用户接收人选择。
- 当前不存在 A 的权限矩阵、状态机和 B 的 OpenAPI，不把前端草案作为批准契约。
- 三种方案：只交静态图不利于验证交互；直接编造后端会破坏职责边界；采用独立可交互原型和可替换认证适配层。

## 顺序与文件

1. `frontend/package.json`、Vite/TS/ESLint 配置和入口：验证 install、typecheck、lint、build。
2. `frontend/src/api/`、`stores/`、`router/`、`types/`：实现错误归一化、会话恢复、多角色守卫；测试 401/403/409/422/500、无权限和恢复失败。
3. `frontend/src/views/`、`components/`、`style.css`：登录、四类工作台、详情和审计原型。内存草稿、表单验证、二次确认、筛选、分页及未保存提醒；每个业务页面标明原型来源。
4. `docs/frontend-integration.md`、`docs/user-guide.md`：记录接口缺口、启动和操作步骤，不声称真实闭环完成。
5. 运行 `npm run check`；浏览器检查 1366×768、1920×1080 和关键交互，保存不含真实数据的证据。

## 本批不标记最终 Done 的项目

C-03 真实认证联调；C-04 至 C-07 真实业务与文件上传；C-09 真实四角色端到端、后端权限与审计验证。均需 B 的 OpenAPI 和 A 的规则。
