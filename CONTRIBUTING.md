# GitHub 协作规范

## 分支

- `main`：始终保持可演示、可部署。
- `develop`：日常集成分支。
- `feat/issue-编号-简述`：功能开发。
- `fix/issue-编号-简述`：缺陷修复。
- `docs/issue-编号-简述`：文档修改。

禁止直接向 `main` 推送日常开发代码。每项任务通过 Pull Request 合并，至少由一名非作者成员审查。

## 任务与看板

任务的唯一来源是 [scripts/github/plan.json](scripts/github/plan.json)，由
[scripts/bootstrap-github.ps1](scripts/bootstrap-github.ps1) 幂等同步到 GitHub：

```powershell
powershell -File scripts/bootstrap-github.ps1 -DryRun   # 只看会做什么
powershell -File scripts/bootstrap-github.ps1           # 同步标签、里程碑、Issue
```

- 新增或修改任务时先改 `plan.json` 再执行脚本，不要在网页上手工改标题（会与计划不一致）；
- 脚本按标题判重，重复执行不会产生重复 Issue；
- 令牌解析顺序：`GITHUB_TOKEN` / `GH_TOKEN` 环境变量 → 仓库根 `.env.local` 的 `GITHUB_TOKEN=` → Git 凭据管理器；不接受命令行明文令牌；
- `.env.local` 已被 `.gitignore` 排除，禁止把令牌提交到仓库或粘贴进 Issue/PR；
- Git 凭据管理器里通常是 OAuth 应用令牌，**没有 `project` 权限**，只够同步标签、里程碑和 Issue；需要脚本自动建看板时，请创建勾选 `repo`、`workflow`、`project` 的 classic PAT 并写入 `.env.local`。

看板列与节奏：

| 看板列 | 含义 |
|---|---|
| Backlog | 已登记但本轮不做 |
| Ready | 已拆解、已认领、可以开工 |
| In Progress | 正在做，每名成员同时不超过 2 项 |
| Review | 已完成，等另一名成员审查 |
| Blocked | 被依赖或环境阻塞，必须带 `blocked` 标签并在站会提出 |
| Done | 验收标准逐条通过、证据已归档 |

每周固定节奏：周一站会确认本周 Ready 列表 → 每天 15 分钟站会同步阻塞 → 周五评审
本周增量并更新追踪矩阵 → 复盘后调整 Backlog 优先级。

## Issue 模板

```markdown
## 目标

## 负责人
A / B / C / D

## 依赖任务

## 实现范围

## 交付物

## 验收标准
- [ ]

## 测试与证据
```

## 提交信息

采用以下前缀：

- `feat:` 新功能
- `fix:` 缺陷修复
- `docs:` 文档
- `test:` 测试
- `refactor:` 不改变功能的代码调整
- `chore:` 工程配置

示例：`feat: implement recon record submission (#11)`。

## Pull Request 要求

PR 必须包含：

1. 关联 Issue，使用 `Closes #编号`。
2. 变更目的和实现范围。
3. 测试步骤与结果。
4. 页面改动截图或接口调用证据。
5. 配置、接口和文档是否同步更新。
6. 安全影响说明，尤其是权限、网络和敏感数据。

## Definition of Done

任务同时满足以下条件才可标记为 Done：

- 交付物已进入仓库；
- 验收条件逐条通过；
- 正常路径和关键异常路径已测试；
- 接口、配置或用户文档已同步；
- 一名非作者成员审查通过；
- 没有真实密码、Token、私钥、个人隐私或课程原始资料；
- 合并后 `develop` 可运行，进入 `main` 前端到端演示通过。

## 机密与大文件

- 仅提交 `.env.example`，不提交 `.env`。
- 不提交数据库数据目录、虚拟机镜像、抓包原件或未经脱敏的日志。
- 不提交课程 PDF、DOCX 和教师模板。
- 测试账号不得复用个人账号密码。
