# C 前端实现与联调清单

更新：2026-10-28 · 分支 `feat/c-frontend-live` · 前端 0.2.0
依据：`contracts/openapi/api-gateway.yaml`（基线 1.0，tag `baseline-1.0`）、`docs/rbac.md`、
`docs/workflow.md`、`docs/api-catalog.md`、B 的 `services/STATUS.md`。

## 1. 当前交付边界

C-01 至 C-09 的界面与联调部分**已在真实后端上跑通**：8 个服务 + 真实 `/api/v1` + 真实审计，
浏览器端 31 步端到端验收全部通过（`evidence/ui-e2e-report.json`）。
仍有 3 处只能“如实受限”，见第 4 节缺口清单；其中 1 处是契约缺上传端点，1 处已在本分支修好并请 B 复核。

| 范围 | 状态 | 证据 |
|---|---|---|
| C-01 工程与请求层 | 完成：Vue 3 + Vite + TS，`src/api/client.ts` 统一注入 Token / `X-Role-Context` / `X-Request-ID` / `Idempotency-Key` | `npm run check` 全绿 |
| C-02 界面规范 | 完成：沿用第一批设计系统，补齐真实数据页需要的状态色、AI 面板、冲突提示、调用链 | `evidence/screenshots/` |
| C-03 登录与权限路由 | 完成：真实登录、多角色工作台、越权页、401 清理会话 | 截图 `14-forbidden-page.png` |
| C-04 侦察工作台 | 完成：列表/草稿/编辑/提交指派/证据元数据/详情 | 截图 01–03b |
| C-05 分析工作台 | 完成：待分析列表、报告草稿、AI 人在回路、提交指派 | 截图 04–06 |
| C-06 决策工作台 | 完成：报告读取、指令起草、冲突检查、二次确认下达、状态与结果 | 截图 07–09、13 |
| C-07 执行工作台 | 完成：接收/拒绝/开始/提交结果与证据 | 截图 10–12 |
| C-08 通用体验 | 完成：加载态、防重复提交、409 双语义、422 字段回显、分页筛选、键盘可达 | `src/__tests__/` 22 项 |
| C-09 联调与验证 | 完成：真实四角色链路 + 越权用例 + 真实审计还原 | `evidence/ui-e2e-report.json` |
| C-10 用户手册 | 完成：`docs/user-guide.md` 已改写为真实系统版本 | — |

## 2. 前端怎么拿到真实数据

```
浏览器 ──/api/v1──▶ Vite dev proxy（开发）或 nginx（部署）──▶ Gateway:8000 ──▶ 8 个服务
```

- 浏览器**只与 Gateway 通信**，不直连任何服务端口（`docs/api-catalog.md` 第 4 节）。
- 后端没有任何 CORS 中间件，因此前端统一用**同源** `/api/v1`：开发由 Vite 反代，部署由 `deploy/nginx/conf.d/nis.conf` 反代。
- 类型不手写：`npm run generate:api` 从 `contracts/openapi/api-gateway.yaml` 生成 `src/api/schema.d.ts`（openapi-typescript），
  `src/api/types.ts` 只做别名与中文标签。契约改了就重新生成，字段名不会各写一套。

接口映射（operationId → 前端函数）在 `src/api/endpoints.ts`，按域分 6 组：
`authApi`、`candidateApi`、`reconApi`、`reportApi`、`commandApi`、`assignmentApi`、`aiApi`、`auditApi`。

关键实现约定：

| 约定 | 位置 | 说明 |
|---|---|---|
| 错误体归一化 | `client.ts#parseError` | 解析 `{code, message, request_id, details.issues[]}`；按 `code` 区分 `VERSION_CONFLICT` 与 `WORKFLOW_CONFLICT` |
| 字段错误回显 | 各面板 `errors` 映射 | 422 的 `details.issues[].field` 直接绑定到对应输入框 |
| 幂等键复用 | 面板内 `createKey` / `submitKey` / `issueKey` / `completeKey` | 同一次提交重试复用同一把键；成功后清空，下一次操作重新生成 |
| 乐观锁 | 所有 PATCH / 状态转换 | 一律带 `expected_version`，410 行以上代码里没有无版本写入 |
| 多角色上下文 | `stores/session.ts#roleContext` | 多角色用户必带 `X-Role-Context`，单角色省略（与 B 的实现一致，见缺口 G5） |
| 证据下载 | `client.ts#requestBlob` | 受控目录不能公开挂静态路径，只能带 Token 取 Blob 再存盘 |

## 3. 本地联调怎么跑（Windows，不用 Docker）

```powershell
# 1. 后端依赖（Python 3.12，3.11.0a7 上 pip 解析 PyPI 会报错）
python -m venv .venv
.\.venv\Scripts\python -m pip install -r services/requirements.txt

# 2. 本地 .env（已被 .gitignore 排除）：口令自己定
#    APP_ENV=development / NIS_ADMIN_PASSWORD=... / NIS_DEMO_PASSWORD=...

# 3. 建表 + IAM 种子（7 个 SQLite 库，落在 .localdata/）
python scripts/dev_stack.py init

# 4. 起 8 个服务（Ctrl+C 全停）
python scripts/dev_stack.py run
python scripts/dev_stack.py status

# 5. 前端
cd frontend
npm install
Copy-Item .env.example .env        # VITE_API_BASE_URL=/api/v1
npm run dev                        # 终端会打印实际端口
```

`scripts/dev_stack.py` 是 C 为联调新增的**开发用启动器**（只建表、写种子、起进程，不改任何服务代码）。
正式环境仍走 D 的 `deploy/docker-compose.yml` + MySQL。

本机注意：如果 8000 已被别的进程占用，在 `.env` 里加 `GATEWAY_PORT=8010`，并在 `frontend/.env` 里写
`VITE_DEV_API_TARGET=http://127.0.0.1:8010`；否则前端会打到别人的服务上（本次联调就是这么做的）。

## 4. 需要 A / B / D 确认的缺口

### G1（已修，请 B 复核）退出接口 204 带响应体

- 现象：`POST /api/v1/auth/logout` 返回 204，但 `JSONResponse(None, status_code=204)` 会写出字面量 `null`，
  uvicorn 抛 `RuntimeError: Response content longer than Content-Length`，浏览器侧表现为请求失败（`net::ERR_ABORTED`）。
- 修复：`services/api-gateway/app/routes_auth.py` 改为 `return Response(status_code=204)`。
- 影响面：仅退出接口；C 端在此之前已经做到“退出失败也清本地会话”，但控制台会一直报错，不适合答辩现场。

### G2 证据没有上传端点（影响 C-04 / C-07 的“上传证据”）

- 契约现状：只有 `EvidenceItemInput{file_name, media_type, size_bytes, sha256}` 与两个下载接口；
  服务端把 `storage_ref` 记成 `recon/<id>/<文件名>`，但**不接收文件本体**，因此下载必然 404。
- C 的处理：浏览器内算 sha256 提交元数据；下载失败时明确提示“文件不在受控目录”，不假装成功。
- 需要 A/B 决策：新增 `POST /api/v1/recon-records/{id}/evidence`（multipart）与执行侧同类接口，
  或明确“本期只演示元数据”。在契约变更前，前端不会自己发明上传地址。

### G3 `ai_content_confirmed` 未进公共契约

- 实现：Gateway 的 `AnalysisReportSubmitRequest.ai_content_confirmed` 默认 false（fail-closed），
  B 已在 `services/STATUS.md` 记录，A 的 `api-gateway.yaml` 尚未补该字段。
- C 的处理：按实现传 `true`，并在提交确认区强制勾选“我已逐条处理 AI 建议”。契约补齐后无需改前端。

### G4 `scripts/seed_demo_data.py` 对多角色账号失败

- 现象：`admin` 有 `administrator + decision_maker` 两个角色，`GET /admin/roles` 返回
  403 `该账号拥有多个角色，请求必须携带 X-Role-Context`，脚本没有带该头，`--with-loop` 走不下去。
- 建议：脚本的 `Client` 增加可选 `role_context`，管理类请求固定带 `administrator`。
- C 的绕行：联调用自建探针脚本按四角色直接调 API（`tests/ui/` 里的验收脚本同样按 UI 走，不受影响）。

### G5 文档与实现不一致（A 的清单待改）

- `docs/api-catalog.md` 第 1 节写 `X-Role-Context` 可选，实现是“多角色必填”，B 已在 Issue #26 上报。
- `GET /recon-records`、`GET /commands` 的 `priority` 过滤在 Gateway 本地过滤 `items`，`total` 仍是未过滤值，
  前端因此**只用服务端 `status` 过滤**，优先级只在当前页展示，避免翻页数字对不上。

### G6 证据下载 404 与“无权查看”同码，需要 D 确认受控目录可见性

- 证据目录（`EVIDENCE_ROOT`）由 D 挂卷并纳入备份；目录缺失或文件缺失都返回 `RESOURCE_NOT_FOUND`，
  前端无法区分“没权限”和“文件没入库”，只能按后者提示。演示前请 D 确认目录存在。

## 5. 验证结果（本机实测，命令与输出）

| 检查 | 命令 | 结果 |
|---|---|---|
| 后端测试 | `python -m pytest tests -q` | 129 passed（51s，内存 SQLite） |
| 契约校验 | `python scripts/validate_contracts.py` | 8 个文档 / 103 路径 / 127 操作通过 |
| 前端全检 | `cd frontend; npm run check` | lint + vue-tsc + 22 项 vitest + build 全通过 |
| 端到端 | `python tests/ui/e2e_four_roles.py` | 31 步全通过，0 控制台错误，0 失败请求 |
| 服务健康 | `python scripts/dev_stack.py status` | 8 个服务 `/health/ready` 全 200 |

详细证据见 [evidence/frontend-c-validation.md](../evidence/frontend-c-validation.md)。

## 6. 下一批可以做（不在本次范围）

1. 契约补上传端点后，把证据从“元数据”升级为真实上传 + 校验 sha256 一致。
2. 多角色用户的“角色上下文”可视化再强化（当前只在顶栏显示）。
3. 表格列宽在超长中文标题下的换行策略（已有 `overflow-wrap`，但列宽仍会跳动）。
4. 把 `tests/ui` 的验收脚本接进 CI（需要先有可用的后端测试栈或 compose 环境）。
