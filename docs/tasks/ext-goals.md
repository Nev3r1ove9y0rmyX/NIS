# 扩展目标补强：给 B / C 的可执行任务说明

更新：2026-11-01 · 编写：A · 对应 Issue #45、#46、#47

这三个任务是**中期验收之后可申报的扩展目标**，不影响基础分；如果时间紧，优先级低于 D 的三域网络。
完成后可申报的扩展从 2 项增加到 5 项（软件工程、数据安全、细粒度权限、限时角色、优先级标红）。

## 通用约束（三条任务都适用）

1. **不改契约**：`contracts/` 下任何文件都不动；如果发现接口不够用，先在 Issue 里说明，由 A 决定是否走变更流程。
2. **不改枚举**：状态、优先级、角色代码都按 `common.yaml` 现有取值。
3. **不引入新依赖**：前端不新增 UI 组件库，后端不新增排序相关库。
4. **不跨模块改动**：只改自己负责的目录，需要别人配合时在 Issue 里 @ 对方。
5. 提交前本地必过：B 跑 `python -m pytest tests -q`；C 跑 `npm run typecheck && npm test && npm run build`。

---

## 任务 1（B）：#46 侦察与指令列表按优先级排序

**目标**：让 `urgent` 任务排在 `normal` 前面，支撑扩展目标“系统优先推送高优先级任务”。

**改动文件**

| 文件 | 改动 |
|---|---|
| `services/recon-service/app/service.py` | 侦察记录列表 `order_by` 增加优先级在前 |
| `services/decision-service/app/service.py` | 指令列表（两处 `order_by`）同样处理 |
| `tests/test_recon_analysis.py` 或新增 | 加一条排序断言 |

**实现要点**

```python
# 关键：布尔表达式在 MySQL/SQLite 都把 True 排前，避免用 CASE WHEN
stmt = stmt.order_by(
    (ReconRecord.priority == "urgent").desc(),   # urgent 在前
    ReconRecord.updated_at.desc(),
)
```

- 分页参数、`total` 计算、`page/page_size` 语义**保持不变**；
- 不要改动 `ticket`/`record_no` 生成逻辑；
- 如果 SQLAlchemy 对布尔排序报错（SQLite 正常，MySQL 也支持），可退化为
  `case((ReconRecord.priority == "urgent", 0), else_=1)` 升序，并把理由写在 PR 里。

**验收标准**

- [ ] 同一用户同时有 urgent 与 normal 记录时，列表首条为 urgent；
- [ ] 分页第 2 页不重复、不遗漏（可用 3 页数据验证）；
- [ ] `pytest` 全绿，新增断言至少覆盖“urgent 排前 + 分页稳定”；
- [ ] 契约不变，`python scripts/validate_contracts.py` 通过。

**预计**：2–3 小时。**依赖**：无。**完成后**：把 PR 链接贴到 #46，并把 #47 的前端演示数据准备好（造一条 urgent 记录）。

---

## 任务 2（C）：#47 紧急任务的红色样式与列表提示

**目标**：四个工作台的列表里，`priority === 'urgent'` 的任务有稳定可见的红色标识。

**改动文件**

| 文件 | 改动 |
|---|---|
| `frontend/src/components/PriorityTag.vue`（新增） | 单一职责的小标签组件 |
| `frontend/src/features/*/…Panel.vue` | 侦察/分析/决策/执行四处列表项使用该组件 |
| `frontend/src/style.css` | 两个 CSS 变量（红底、红字），与现有主题保持一致 |

**实现要点**

```vue
<!-- PriorityTag.vue 草图 -->
<script setup lang="ts">
defineProps<{ priority: 'normal' | 'urgent' | string }>()
</script>
<template>
  <span v-if="priority === 'urgent'" class="pill pill-urgent">紧急</span>
</template>
```

- 普通任务**不渲染**该标签（避免满屏红色）；
- 颜色用主题变量，不要写死 `#f00`；建议 `--danger-bg: #fee2e2; --danger-fg: #b91c1c;`；
- `StatusPill` 已有状态配色，优先级标签要与它视觉区分（建议形状或位置不同）。
- 若列表项已有 `priorityNames` 文本，可保留文本、只把颜色改为红色，避免信息重复。

**验收标准**

- [ ] 四个工作台列表中，紧急任务有红色标识，普通任务无红色（四张截图）；
- [ ] 深色/浅色背景下文字可读（如项目只做浅色，说明即可）；
- [ ] `npm run typecheck && npm test && npm run build` 通过；
- [ ] 不修改 `api/schema.d.ts`（由契约生成，不能手改）。

**预计**：3–4 小时。**依赖**：#46 造出的 urgent 数据用于截图；没有也能先用本地假数据做样式。

---

## 任务 3（C）：#45 权限管理页（角色权限勾选 + 用户角色到期时间）

**目标**：让“细粒度功能权限”和“限时角色自动回收”两项扩展可现场演示。后端已就绪，**不需要 B 改代码**。

**可用接口（全部在 `contracts/openapi/api-gateway.yaml` 的“管理”标签下）**

| 用途 | 请求 |
|---|---|
| 角色列表 | `GET /api/v1/admin/roles` → `{items:[{id,code,name,is_system,permissions[]}]}` |
| 权限目录 | `GET /api/v1/admin/permissions` → `{items:[{code,name,domain}]}` |
| 替换角色权限 | `PUT /api/v1/admin/roles/{role_id}/permissions`，body `{permission_codes:[...]}` |
| 用户列表 | `GET /api/v1/admin/users?page=1&page_size=50` |
| 给用户加角色 | `POST /api/v1/admin/users/{user_id}/roles`，body `{role_code, expires_at?}` |

**关键约束**

- 管理接口要求**多角色账号**携带 `X-Role-Context: administrator`——现有 `stores/session.ts` 的 `roleContext()` 已会自动带，确认登录后 `administrator` 在角色列表里即可；
- 保存权限是**整组替换**（不是增量），提交前要把勾选结果整体提交；
- 到期时间用 ISO 8601 UTC 字符串（例：`2026-11-01T12:00:00Z`），前端日期时间控件转 UTC 再发；
- 页面必须按 `iam:manage` 做路由守卫，非管理员访问显示 `/forbidden`。

**实现要点**

| 文件 | 改动 |
|---|---|
| `frontend/src/views/AdminView.vue`（新增） | 两个页签：角色权限、用户角色 |
| `frontend/src/router/index.ts` | 增加 `/admin` 路由与 `workspace: 'admin'` 守卫（复用现有 `allowedWorkspaces`） |
| `frontend/src/api/endpoints.ts` | 增加 4 个管理接口封装（沿用现有 `client.ts`） |

页面最小可用即可：左侧角色列表 → 右侧权限复选（按 `domain` 分组）→ 保存；下方用户列表 → “加角色”弹窗（选角色 + 可选到期时间）。

**验收标准**

- [ ] 能为某角色取消 `analysis:read_assigned`，保存后该角色账号调用分析列表返回 403（截图 + 接口返回）；
- [ ] 能给用户设置 1 分钟后到期的角色，到期后该用户调用受控接口返回 403（截图两次）；
- [ ] 非 `iam:manage` 账号访问 `/admin` 被守卫拦到 `/forbidden`；
- [ ] `typecheck / test / build` 通过；不手改 `schema.d.ts`。

**预计**：1 天（页面 0.5 天 + 自测与截图 0.5 天）。**依赖**：无（可先用现有 `admin` 账号）。

---

## 提交与评审要求

1. 分支：`feat/45-admin-page`、`feat/46-priority-order`、`feat/47-priority-tag`；
2. PR 标题写 `Closes #45` 等，正文贴验收证据（命令输出或截图路径）；
3. 合并前确认三套 CI 至少 `contracts` 与对应语言门禁通过；
4. 任一任务如果判断做不完，**在 Issue 里提前说**，不要到验收前一天才说——A 可以据此调整申报口径。

## 时间安排建议

| 天 | B | C |
|---|---|---|
| D1 | #46 排序 + 测试 | #47 标红样式 |
| D2 | 回归、准备 urgent 演示数据 | #45 页面骨架 + 角色权限 |
| D3 | 配合 A 联调 | #45 到期时间 + 自测截图 |

如果只有一天：**B 做 #46，C 做 #47**，这两项合起来就能演示“分级推送 + 紧急标红”；#45 留到验收后。
