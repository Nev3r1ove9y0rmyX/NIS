# 后端交付状态（成员 B）

> 更新：2026-10-27 · 对应分支链 `feat/7 → 8 → 9 → 10 → 11 → contract-tests`

## 一句话

8 个服务（gateway + iam/recon/analysis/decision/execution/ai/audit）的骨架、迁移、认证授权、
四段业务链、审计与调用链、AI 建议、种子数据与自动化测试**已全部实现并通过验证**；
按 Issue 拆成 6 个 PR 等待评审合并。

## 各服务实现情况

| 服务 | 端口 | 契约内接口 | 未实现 | 备注 |
|---|---:|---|---|---|
| API Gateway | 8000 | 全部 | — | 含两个证据下载的受控代理 |
| IAM & Organization | 8001 | 全部 | — | RS256 私钥只在此服务 |
| Reconnaissance | 8002 | 全部 | — | 提交即指派，状态机 `draft→submitting→assigned` |
| Analysis | 8003 | 全部 | — | 侦察快照由服务端生成 |
| Decision | 8004 | 全部 | — | 总体状态唯一重算点（D-01） |
| Execution | 8005 | 全部 | — | 只维护个人状态，回写决策侧 |
| AI Assistance | 8006 | 全部 | — | 规则模板，`AI_ENABLED=false` 可降级 |
| Audit | 8007 | 全部 | — | `audit_events` 只追加；查询需 `audit:read` |

证据文件按决策 D-02 实现在受控目录（`EVIDENCE_ROOT`）：数据库只存元数据与 `storage_ref`，
下载经业务接口鉴权后用 `FileResponse` 流式返回，路径解析拒绝绝对路径与 `..` 穿越，每次下载写
`evidence.download` 审计（含 sha256）。

## 怎么跑（Windows 本地）

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r services/requirements.txt

# 本地 MySQL 8（任意方式），建 7 个 Schema 与运行/迁移账号后：
.venv/Scripts/python scripts/migrate_all.py --verify      # 迁移并核对表
set NIS_ADMIN_PASSWORD=... & set NIS_DEMO_PASSWORD=...
.venv/Scripts/python scripts/seed_data.py                 # 种子（幂等）

# 起服务：每个服务在自己的目录下
cd services/iam-service && set PYTHONPATH=..;..\_shared && python -m uvicorn app.main:app --port 8001
```

四类演示账号：`recon01` / `analyst01` / `dmaker01` / `exec01`（同口令，由 `NIS_DEMO_PASSWORD` 注入），
管理员 `admin`（`NIS_ADMIN_PASSWORD`）。同一账号多角色时请求必须带 `X-Role-Context`。

## 验证命令与最近一次结果

| 命令 | 结果 |
|---|---|
| `python -m pytest tests -q` | **129 passed** |
| `python scripts/validate_contracts.py` | 8 个文档 / 103 路径 / 127 操作，通过 |
| `python scripts/check_doc_links.py` | 117 条相对链接通过 |
| `python scripts/migrate_all.py --verify` | 7 个 Schema / 21 张表 |
| `python scripts/check_db_privileges.py` | 7 个 Schema 账号权限符合 D-06 |
| `python scripts/seed_data.py`（跑两遍） | 第二遍全部 +0（幂等） |

真实栈端到端（8 个进程 + MySQL）：侦察 → 分析 → 决策 → 执行全链路可跑，
指令状态按 `issued → partially_accepted → accepted → executing → partially_completed → completed` 变化，
审计可用 `request_id` 还原跨服务调用链，AI 建议走「pending → 人工处理」并在重复处理时返回 409。

## 评审指引（按此顺序合并）

| 顺序 | PR | 内容 | 关注点 |
|---:|---|---|---|
| 1 | #25 | 骨架 / 迁移 / 种子 | 数据模型逐列对齐；Dockerfile 构建上下文为仓库根 |
| 2 | #27 | 认证与 RBAC | 权限每请求向 IAM 取（改权限立即生效）；退出为无状态退出 |
| 3 | #28 | 侦察与分析 | 快照来源、越权返回 404、幂等提交 |
| 4 | #29 | 指令与执行 | 冲突确认、D-01 单一汇总入口、重复完成 409 |
| 5 | #34 | 审计与 AI | 调用链、`audit:read`、AI 降级与人在回路 |
| 6 | #35 | 契约一致性测试 | 不许发明路由/静默漏实现 |

每次只需要把下一个 PR 的 base 改成 `develop`，diff 不会叠加。

## 待他人决策 / 协作

| 事项 | 需要谁 | 状态 |
|---|---|---|
| 审计账号需 `audit_trace_index` 的 UPDATE（`audit_events` 仍只追加） | D 同步 `deploy/mysql/init/` | 代码与检查脚本已就绪 |
| `iam-service.yaml` 补 `DELETE /internal/v1/users/{id}/roles/{role_code}` | A | 已在 Issue #26 上报，代码已实现 |
| Gateway 的 `submitAnalysisReport` 缺 `ai_content_confirmed` 字段 | A | 当前按 fail-closed（默认 false）实现 |
| 证据下载的受控目录与备份范围 | D | 代码已实现（`EVIDENCE_ROOT`），待 D 挂卷与纳入备份 |
| `X-Role-Context` 在 api-catalog 里仍写"可选" | A | 实现按"多角色必填"，已在 #26 上报 |

## 已知限制

- 测试跑在内存 SQLite；MySQL 专项验证靠迁移脚本与真机连通，CI 接入 MySQL service 容器建议与 D 的 #17/#32 一起做。
- 审计写入接口只靠容器网络隔离，未做服务令牌校验（建议与 D 的部署加固一起）。
- 令牌吊销为无状态（60 分钟 TTL + 每请求状态检查）；要即时吊销需新增令牌表，走变更流程。
- AI 建议是可复现规则模板，未接外部模型；替换只改 `services/ai-service/app/service.py` 的 `generate()`。
