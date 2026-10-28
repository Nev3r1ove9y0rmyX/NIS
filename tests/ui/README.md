# UI 端到端验收脚本

主责：成员 C。用途：在**真实后端**上把四角色业务链跑一遍，产出截图与机器可读报告，
用于 C-09 联调验收、答辩预演与回归。

## 它做什么

`e2e_four_roles.py` 用 Playwright 驱动真实 Chromium，按角色顺序操作界面：

```
侦察员登录 → 建记录 → 存草稿 → 请求/接受 AI 建议 → 提交并指派分析员
分析员登录 → 写报告 → 修改并采用 AI 建议 → 提交并指派决策员
决策员登录 → 建指令 → 冲突检查 → 选执行员 → 二次确认下达
执行员登录 → 接收 → 开始 → 提交结果
决策员回看 → 指令总体状态与各执行员结果
侦察员访问决策工作台 → 403 页面
管理员登录 → 审计事件 → 按 request_id 还原跨服务调用链
```

同时验证 1366×768 与 1920×1080 两种桌面尺寸，并记录控制台错误与失败请求。

## 怎么跑

```powershell
# 1. 起后端（二选一）
python scripts/dev_stack.py run          # 本机 SQLite 全栈
docker compose -f deploy/docker-compose.yml up -d   # 正式拓扑

# 2. 起前端
cd frontend; npm run dev

# 3. 跑验收（端口按终端实际输出改）
$env:NIS_UI_BASE="http://127.0.0.1:5173"
python tests/ui/e2e_four_roles.py
```

依赖：`pip install playwright && playwright install chromium`；仓库根 `.env` 里要有
`NIS_ADMIN_PASSWORD` 与 `NIS_DEMO_PASSWORD`（脚本也接受同名环境变量）。

## 产物

| 路径 | 内容 |
|---|---|
| `evidence/screenshots/01..16-*.png` | 关键页面截图，按流程编号 |
| `evidence/ui-e2e-report.json` | 每步耗时、控制台错误、失败请求、被导航中断的请求 |
| `evidence/screenshots/99-failure-state.png` | 只在失败时出现，用于定位 |

退出码 0 表示所有步骤通过；1 表示有步骤失败（报告里 `steps` 会带 `FAILED` 与堆栈尾部）。

## 注意

- 脚本会**真实写入业务数据**（每次运行生成一条完整链）。演示前可以重置：
  `python scripts/dev_stack.py stop && rm -r .localdata && python scripts/dev_stack.py init`。
- 脚本不修改服务代码，也不读数据库；它对系统的判断完全来自页面与接口响应。
- 目前只覆盖 Chromium；D 的网络验收脚本在 `tests/network/`，两者互补。
