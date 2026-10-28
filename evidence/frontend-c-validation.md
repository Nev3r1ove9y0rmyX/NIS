# C 前端验证记录（第二批：真实接口联调）

日期：2026-10-28 · 机器：Windows 11 + PowerShell · Node 24.18.0 / npm 11.16.0 · Python 3.12（venv）
前端 0.2.0 · 后端 `feat/evidence-download` 分支（B 的 7 个服务 + Gateway） · 契约基线 1.0

本文件只记录**实际运行**的结果。没有跑过的项一律写在“未执行”里，不给结论。

## 1. 环境与数据

| 项 | 实测 |
|---|---|
| 后端依赖安装 | `python -m venv .venv` + `pip install -r services/requirements.txt` 成功（fastapi 0.162.0 / sqlalchemy 2.1.6 / uvicorn 0.54.0） |
| 数据库 | 本机无 Docker/MySQL 可用，改用 `scripts/dev_stack.py init` 建 7 个 SQLite 库（`.localdata/*.db`），共 21 张表，与 `docs/data-model.md` 的 Schema 划分一致（iam 6 / recon 3 / analysis 3 / decision 3 / execution 2 / ai 2 / audit 2） |
| IAM 种子 | `种子完成：organizations+5，permissions+18，roles+5，role_permissions+24，users+8，user_roles+9` |
| 8 服务启动 | `dev_stack.py status`：iam/audit/recon/analysis/decision/execution/ai/gateway 全部 `/health/ready` 200 |
| Gateway 端口 | 本机 8000 被一个 2 天前的遗留 `uvicorn` 占用，改用 `GATEWAY_PORT=8010`，前端 `VITE_DEV_API_TARGET` 同步 |

## 2. 后端自带验证（复跑，确认联调基座是好的）

```text
$ python -m pytest tests -q
129 passed, 1 warning in 51.04s

$ python scripts/validate_contracts.py
契约文件：8 个 OpenAPI 文档，103 条路径，127 个操作
共享枚举：21 个组件
校验通过：未发现结构、引用或重复键问题。
```

## 3. 前端检查（全部实际执行）

```text
$ cd frontend; npm run check
> nis-frontend@0.2.0 lint      → eslint . ：0 error / 0 warning
> nis-frontend@0.2.0 typecheck → vue-tsc --noEmit ：通过
> nis-frontend@0.2.0 test      → vitest run ：2 个文件 22 项全部通过（client 10 + domain 12）
> nis-frontend@0.2.0 build     → vue-tsc + vite build ：
    dist/index.html                  0.99 kB
    dist/assets/index-*.css         26.60 kB │ gzip  6.75 kB
    dist/assets/index-*.js         214.89 kB │ gzip 70.40 kB
    ✓ built in 1.78s
```

测试覆盖（`src/__tests__/`）：

| 文件 | 覆盖点 |
|---|---|
| `client.test.ts` | `details.issues` 字段映射、409 双语义（VERSION/WORKFLOW）、后端中文提示直用、HTML/堆栈不回显、未知状态码兜底、Token 与 `X-Role-Context`/`X-Request-ID`/`Idempotency-Key` 注入、204 空体、401 触发失效回调、网络异常归一化、拒绝站外路径 |
| `domain.test.ts` | 角色→工作台映射（含未知角色忽略）、状态中文名与色调、身份结构校验（无角色拒绝）、单角色省略/多角色必带角色上下文、四类表单校验限额与枚举、证据文件类型/大小、`datetime-local` 与 ISO UTC 互转 |

## 4. 浏览器端到端验收（真实接口，无 mock）

命令：`python tests/ui/e2e_four_roles.py`（Playwright 1.59 + Chromium，1920×1080 + 1366×768）

```text
>>> 侦察员登录并进入工作台                    ok
>>> 侦察工作台截图 1920×1080                   ok
>>> 侦察工作台窄屏截图 1366×768                ok
>>> 新建侦察记录并保存草稿                     ok
>>> 请求 AI 建议并人工接受                     ok
>>> 侦察面板（含 AI 结论）截图                  ok
>>> 提交侦察记录并指派分析员                    ok
>>> 关闭面板并确认列表状态（已指派待分析）        ok
>>> 退出并登录分析员                          ok
>>> 分析工作台截图                            ok
>>> 分析员创建报告草稿                        ok
>>> AI 建议人工修改后采用                     ok
>>> 提交分析报告并指派决策员                    ok
>>> 退出并登录决策员                          ok
>>> 决策工作台截图                            ok
>>> 决策员创建指令草稿                        ok
>>> 冲突检查并下达指令                        ok
>>> 关闭指令面板并确认状态（已下达待接收）        ok
>>> 退出并登录执行员                          ok
>>> 执行工作台截图                            ok
>>> 接收 → 开始 → 提交执行结果                  ok
>>> 关闭执行面板并确认完成                      ok
>>> 重新登录决策员回看结果                      ok
>>> 决策员查看指令状态与执行结果                 ok
>>> 侦察员访问决策工作台被拦截（403 页面）        ok
>>> 登录管理员（管理权限束）                    ok
>>> 审计工作台截图                            ok
>>> 按请求 ID 还原调用链                       ok
报告：ok=True，steps=31
控制台错误 0 条，请求失败 0 条
```

被浏览器记为 `net::ERR_ABORTED` 的 4 条请求全部来自验收脚本自身的整页跳转（`page.goto` 打断在途列表请求），
服务端无 4xx/5xx，审计里也没有失败记录。

机器报告：[ui-e2e-report.json](ui-e2e-report.json)。截图：`evidence/screenshots/`（18 张，按流程编号）。

| 截图 | 内容 |
|---|---|
| `01-recon-workspace-1920.png` / `01b-...-1366.png` | 侦察工作台两种桌面尺寸 |
| `02-recon-panel-ai.png` | 侦察面板 + AI 建议已接受（建议原文 / 模型 / 置信度 / 人工确认时间） |
| `03-recon-submit-confirm.png` / `03b-recon-list-assigned.png` | 提交确认（勾选分析员）与列表状态变 `已指派待分析` |
| `04-analysis-workspace.png` / `05-analysis-panel-ai.png` | 分析工作台、报告面板 + AI 修改后采用 |
| `06-analysis-submit-confirm.png` | 提交确认（勾选决策员 + AI 已处理确认） |
| `07-decision-workspace.png` / `08-decision-issue-confirm.png` | 决策工作台、冲突检查 + 选择执行员 + 二次确认 |
| `09-decision-command-list.png` / `13-decision-command-status.png` | 指令列表状态、指令详情（总体状态 / 各执行员状态 / 执行结果） |
| `10-execution-workspace.png` / `11-execution-result-form.png` / `12-execution-completed.png` | 执行工作台、结果表单、完成态 |
| `14-forbidden-page.png` | 侦察员直接访问决策工作台的 403 页面 |
| `15-audit-events.png` / `16-audit-trace.png` | 审计事件列表、按请求 ID 还原的两服务调用链 |

## 5. 接口层反向用例（真实调用，非 UI）

| 用例 | 实测响应 |
|---|---|
| 侦察员读 `/analysis-reports` | 403 `FORBIDDEN`（`details.permission=analysis:read_assigned`） |
| 侦察员读 `/commands` | 403 `FORBIDDEN` |
| 分析员读 `/commands` | 403 `FORBIDDEN` |
| 执行员读 `/analysis-reports` | 403 `FORBIDDEN` |
| 多角色账号（admin）不带 `X-Role-Context` 访问 `/admin/roles` | 403 `该账号拥有多个角色，请求必须携带 X-Role-Context`（`details.roles=[administrator, decision_maker]`） |
| 重复 `Idempotency-Key` 下达同一指令 | 返回同一 `command_id`，未产生第二份分配 |
| 分析员可见记录范围 | 只看到指派给自己的那 1 条；访问未指派记录返回 404 `RESOURCE_NOT_FOUND` |

## 6. 未执行 / 受限项（如实记录）

| 项 | 原因 |
|---|---|
| Docker Compose + MySQL 全栈 | 本机 Docker daemon 未运行；本次用 `scripts/dev_stack.py`（SQLite）跑通同一套服务代码，正式环境仍以 `deploy/` 为准 |
| 证据真实上传 | 契约没有上传端点（见 [联调清单](../docs/frontend-integration.md) G2），只能提交元数据 |
| 三域网络下的前端访问 | 需要 D 的 iKuai 环境；本次是本机回环 |
| Safari / Firefox 兼容性 | 只做了 Chromium（课程演示与 D 的验收环境一致） |
| 移动端布局 | 只保证 1366×768 与 1920×1080 桌面尺寸（C-02 的范围） |
| `npm ci` 复现安装 | 本次为 `npm install` 生成 `package-lock.json`；建议后续统一 `npm ci` |

## 7. 结论

C-03 至 C-09 的界面与联调部分在真实后端上闭环：四类角色都能在界面上完成自己的动作，
页面状态与 `docs/workflow.md` 的状态机一致，越权被后端拒绝并在前端给出可理解提示，
审计可以按 `X-Request-ID` 还原跨服务调用链。剩余问题集中在契约缺口（G1–G6），不是前端逻辑缺陷。
