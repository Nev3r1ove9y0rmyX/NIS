"""四角色端到端验收（成员 C，C-09）。

用 Playwright 驱动真实 Chromium，访问本机运行的 Vite 前端 + 8 个后端服务，
按「侦察 → 分析 → 决策 → 执行 → 审计」跑通一条完整业务链，全程走真实 /api/v1，
没有任何 mock；同时验证越权页面与 1366×768 窄屏布局。

前置条件：
  1. 后端栈已启动（python scripts/dev_stack.py run，或 docker compose up -d）；
  2. 前端 dev server 已启动（cd frontend && npm run dev）；
  3. 仓库根有本地 .env（NIS_ADMIN_PASSWORD / NIS_DEMO_PASSWORD 由部署者设置）；
  4. Python 侧装了 playwright 与 chromium（pip install playwright && playwright install chromium）。

用法：
  set NIS_UI_BASE=http://127.0.0.1:5173        # 前端地址；本机 5173 被占用时按实际端口改
  python tests/ui/e2e_four_roles.py

输出：
  evidence/screenshots/*.png        关键页面截图（可直接放进报告与答辩材料）
  evidence/ui-e2e-report.json       每步耗时、控制台错误、失败请求、被导航中断的请求

退出码：0 全部步骤通过；1 有步骤失败（失败截图另存 99-failure-state.png）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SHOT_DIR = ROOT / "evidence" / "screenshots"
BASE = os.environ.get("NIS_UI_BASE", "http://127.0.0.1:5173")
REPORT = ROOT / "evidence" / "ui-e2e-report.json"

steps: list[dict[str, object]] = []
console_errors: list[str] = []
failed_requests: list[str] = []
aborted_requests: list[str] = []


def env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


ENV = env()
DEMO_PASSWORD = os.environ.get("NIS_DEMO_PASSWORD") or ENV["NIS_DEMO_PASSWORD"]
ADMIN_PASSWORD = os.environ.get("NIS_ADMIN_PASSWORD") or ENV["NIS_ADMIN_PASSWORD"]


def step(name: str, action) -> None:  # noqa: ANN001
    started = time.time()
    print(f"\n>>> {name}")
    action()
    elapsed = round(time.time() - started, 1)
    steps.append({"step": name, "ok": True, "seconds": elapsed})
    print(f"    ok ({elapsed}s)")


def shot(page, name: str) -> Path:  # noqa: ANN001
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"    shot -> {path.name}")
    return path


def login(page, username: str, password: str) -> None:  # noqa: ANN001
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.get_by_label("用户名").fill(username)
    page.get_by_label("密码").fill(password)
    page.get_by_role("button", name=re.compile("登录工作台")).click()
    page.wait_for_url(re.compile(r"/w/(recon|analysis|decision|execution|audit)"), timeout=20000)
    page.wait_for_load_state("networkidle")


def logout(page) -> None:  # noqa: ANN001
    button = page.get_by_role("button", name="退出")
    if button.count():
        button.first.click()
        try:
            page.wait_for_url(re.compile(r"/login"), timeout=8000)
            return
        except Exception:  # noqa: BLE001 - 消息页没有退出按钮时继续走显式跳转
            pass
    page.goto(f"{BASE}/login", wait_until="networkidle")
    page.wait_for_url(re.compile(r"/login"), timeout=15000)


def open_dialog(page):  # noqa: ANN001, ANN201
    dialog = page.locator("dialog[open]")
    dialog.wait_for(state="visible", timeout=15000)
    return dialog


def main() -> int:
    with sync_playwright() as play:
        browser = play.chromium.launch()
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
        page = context.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on(
            "requestfailed",
            lambda request: (
                aborted_requests.append(f"{request.method} {request.url}")
                if request.failure and "ERR_ABORTED" in request.failure
                else failed_requests.append(f"{request.method} {request.url} ({request.failure})")
            ),
        )

        try:
            # ---------------------------------------------------------------- 侦察员
            step("侦察员登录并进入工作台", lambda: login(page, "recon01", DEMO_PASSWORD))
            step("侦察工作台截图 1920×1080", lambda: (page.wait_for_timeout(600), shot(page, "01-recon-workspace-1920")))

            def narrow() -> None:
                page.set_viewport_size({"width": 1366, "height": 768})
                page.wait_for_timeout(500)
                shot(page, "01b-recon-workspace-1366")

            step("侦察工作台窄屏截图 1366×768", narrow)
            page.set_viewport_size({"width": 1920, "height": 1080})

            def create_record() -> None:
                page.get_by_role("button", name=re.compile("新建侦察记录")).first.click()
                dialog = open_dialog(page)
                dialog.get_by_label("标题").fill("端到端验收：目标区域活动规律观察")
                dialog.get_by_label("来源类型").select_option("osint")
                dialog.get_by_label("可信度").select_option("medium")
                dialog.get_by_label("优先级").select_option("urgent")
                dialog.get_by_label("来源说明").fill("浏览器验收脚本提交，内容已脱敏")
                dialog.get_by_label("正文").fill(
                    "在课程授权的演示环境中，观察到目标区域每日固定时段出现人员与车辆往返，"
                    "路线相对固定，伴随无线电通联活动。本条由浏览器端验收脚本提交。"
                )
                dialog.get_by_role("button", name=re.compile("保存草稿")).click()
                page.get_by_text(re.compile("草稿已保存")).wait_for(timeout=15000)

            step("新建侦察记录并保存草稿", create_record)

            def ai_accept() -> None:
                dialog = page.locator("dialog[open]")
                dialog.get_by_role("button", name="请求 AI 建议").click()
                dialog.get_by_text("建议原文").wait_for(timeout=15000)
                dialog.get_by_role("button", name="接受建议").click()
                page.get_by_text(re.compile("AI 建议处理结果：已接受")).first.wait_for(timeout=15000)

            step("请求 AI 建议并人工接受", ai_accept)
            step("侦察面板（含 AI 结论）截图", lambda: shot(page, "02-recon-panel-ai"))

            def submit_record() -> None:
                dialog = page.locator("dialog[open]")
                dialog.get_by_role("button", name=re.compile("提交给分析员")).click()
                dialog.get_by_text("指派分析员").wait_for(timeout=15000)
                dialog.locator("label.check-label", has_text="分析员甲").locator("input").first.check()
                shot(page, "03-recon-submit-confirm")
                dialog.get_by_role("button", name="确认提交").click()
                page.get_by_text(re.compile("已提交并指派分析员")).wait_for(timeout=20000)

            step("提交侦察记录并指派分析员", submit_record)

            def close_and_check() -> None:
                page.locator("dialog[open]").get_by_role("button", name="关闭对话框").click()
                page.locator("dialog[open]").wait_for(state="hidden", timeout=10000)
                page.locator("table .status-badge", has_text="已指派待分析").first.wait_for(timeout=15000)
                shot(page, "03b-recon-list-assigned")

            step("关闭面板并确认列表状态", close_and_check)

            # ---------------------------------------------------------------- 分析员
            step("退出并登录分析员", lambda: (logout(page), login(page, "analyst01", DEMO_PASSWORD)))
            step("分析工作台截图", lambda: (page.wait_for_timeout(600), shot(page, "04-analysis-workspace")))

            def write_report() -> None:
                page.get_by_role("button", name=re.compile("写报告")).first.click()
                dialog = open_dialog(page)
                dialog.get_by_label("标题").fill("端到端验收：区域活动规律分析")
                dialog.get_by_label("关键发现").fill("活动时间与路线高度规律，具备固定保障节点特征（浏览器验收数据）。")
                dialog.get_by_label("关联关系").fill("人员往返与车辆调度在同一时段出现，两者存在时间耦合。")
                dialog.get_by_label("建议手段").fill("建议在固定时段前完成观察点部署，并保留影像证据。")
                dialog.get_by_label("风险等级").select_option("medium")
                dialog.get_by_label("优先级").select_option("urgent")
                dialog.get_by_role("button", name=re.compile("保存草稿")).click()
                page.get_by_text(re.compile("报告草稿已保存")).wait_for(timeout=15000)

            step("分析员创建报告草稿", write_report)

            def ai_edit() -> None:
                dialog = page.locator("dialog[open]")
                dialog.get_by_role("button", name="请求 AI 建议").click()
                dialog.get_by_text("建议原文").wait_for(timeout=15000)
                dialog.get_by_role("button", name="修改建议").click()
                dialog.get_by_label("建议标题").fill("人工复核后的关联结论")
                dialog.get_by_role("button", name="修改后采用").click()
                page.get_by_text(re.compile("AI 建议处理结果：已修改")).first.wait_for(timeout=15000)

            step("AI 建议人工修改后采用", ai_edit)
            step("分析面板（含 AI 修改）截图", lambda: shot(page, "05-analysis-panel-ai"))

            def submit_report() -> None:
                dialog = page.locator("dialog[open]")
                dialog.get_by_role("button", name=re.compile("提交给决策员")).click()
                dialog.get_by_text("指派决策员").wait_for(timeout=15000)
                dialog.locator("label.check-label", has_text="决策员甲").locator("input").first.check()
                dialog.locator("label.check-label", has_text="我已逐条处理 AI 建议").locator("input").check()
                shot(page, "06-analysis-submit-confirm")
                dialog.get_by_role("button", name="确认提交").click()
                page.get_by_text(re.compile("已提交并指派决策员")).wait_for(timeout=20000)

            step("提交分析报告并指派决策员", submit_report)

            def close_report() -> None:
                page.locator("dialog[open]").get_by_role("button", name="关闭对话框").click()
                page.locator("dialog[open]").wait_for(state="hidden", timeout=10000)

            step("关闭分析面板", close_report)

            # ---------------------------------------------------------------- 决策员
            step("退出并登录决策员", lambda: (logout(page), login(page, "dmaker01", DEMO_PASSWORD)))
            step("决策工作台截图", lambda: (page.wait_for_timeout(600), shot(page, "07-decision-workspace")))

            def create_command() -> None:
                page.get_by_role("button", name=re.compile("下达指令")).first.click()
                dialog = open_dialog(page)
                dialog.get_by_label("标题").fill("端到端验收：固定时段观察任务")
                dialog.get_by_label("目标").fill("在固定时段获取目标区域活动证据")
                dialog.get_by_label("行动内容").fill(
                    "提前 30 分钟到达观察点，按约定频段通联，只做观察与记录，不主动接触。"
                )
                dialog.get_by_label("优先级").select_option("urgent")
                dialog.get_by_role("button", name=re.compile("保存草稿")).click()
                page.get_by_text(re.compile("指令草稿已保存")).wait_for(timeout=15000)

            step("决策员创建指令草稿", create_command)

            def issue_command() -> None:
                dialog = page.locator("dialog[open]")
                dialog.get_by_role("button", name=re.compile("冲突检查并下达")).click()
                dialog.get_by_text(re.compile("没有发现冲突|发现 ")).first.wait_for(timeout=15000)
                dialog.locator("label.check-label", has_text="执行员甲").locator("input").first.check()
                shot(page, "08-decision-issue-confirm")
                dialog.get_by_role("button", name="确认下达").click()
                page.get_by_text(re.compile("指令已下达")).wait_for(timeout=20000)

            step("冲突检查并下达指令", issue_command)

            def close_command() -> None:
                page.locator("dialog[open]").get_by_role("button", name="关闭对话框").click()
                page.locator("dialog[open]").wait_for(state="hidden", timeout=10000)
                page.get_by_role("tab", name=re.compile("我的行动指令")).click()
                page.wait_for_timeout(800)
                page.locator("table .status-badge", has_text="已下达待接收").first.wait_for(timeout=15000)
                shot(page, "09-decision-command-list")

            step("关闭指令面板并确认状态", close_command)

            # ---------------------------------------------------------------- 执行员
            step("退出并登录执行员", lambda: (logout(page), login(page, "exec01", DEMO_PASSWORD)))
            step("执行工作台截图", lambda: (page.wait_for_timeout(600), shot(page, "10-execution-workspace")))

            def run_assignment() -> None:
                page.get_by_role("button", name=re.compile("接收.*拒绝")).first.click()
                dialog = open_dialog(page)
                dialog.get_by_role("button", name="接收指令").click()
                page.get_by_text(re.compile("已接收指令")).wait_for(timeout=15000)
                dialog.get_by_role("button", name="开始执行").click()
                page.get_by_text(re.compile("已标记开始执行")).wait_for(timeout=15000)
                dialog.get_by_role("button", name="填写结果并提交").click()
                dialog.get_by_label("结论").select_option("success")
                dialog.get_by_label("结果摘要").fill("按计划完成观察，取得 3 段连续记录。")
                dialog.get_by_label("过程与异常").fill("观察期间未发生异常接触，证据已按要求登记。")
                shot(page, "11-execution-result-form")
                dialog.get_by_role("button", name="提交结果").click()
                page.get_by_text(re.compile("执行结果已提交")).wait_for(timeout=20000)

            step("接收 → 开始 → 提交执行结果", run_assignment)

            def close_assignment() -> None:
                shot(page, "12-execution-completed")
                page.locator("dialog[open]").get_by_role("button", name="关闭对话框").click()
                page.wait_for_timeout(600)
                page.locator("table .status-badge", has_text="已完成").first.wait_for(timeout=15000)

            step("关闭执行面板并确认完成", close_assignment)

            # ---------------------------------------------------------------- 决策回看
            step("退出并重新登录决策员回看结果", lambda: (logout(page), login(page, "dmaker01", DEMO_PASSWORD)))

            def review_result() -> None:
                page.get_by_role("tab", name=re.compile("我的行动指令")).click()
                page.wait_for_timeout(800)
                page.get_by_role("button", name=re.compile("查看状态")).first.click()
                dialog = open_dialog(page)
                dialog.get_by_text("执行结果").wait_for(timeout=15000)
                shot(page, "13-decision-command-status")
                dialog.get_by_role("button", name="关闭对话框").click()

            step("决策员查看指令状态与执行结果", review_result)

            # ---------------------------------------------------------------- 越权
            step("退出并登录侦察员验证越权页面", lambda: (logout(page), login(page, "recon01", DEMO_PASSWORD)))

            def forbidden() -> None:
                page.goto(f"{BASE}/w/decision", wait_until="networkidle")
                page.get_by_text("当前角色无权进入这个工作台").wait_for(timeout=15000)
                shot(page, "14-forbidden-page")

            step("侦察员访问决策工作台被拦截", forbidden)

            # ---------------------------------------------------------------- 审计
            step("退出并登录管理员（管理权限束）", lambda: (logout(page), login(page, "admin", ADMIN_PASSWORD)))
            step("审计工作台截图", lambda: (page.wait_for_timeout(1000), shot(page, "15-audit-events")))

            def trace() -> None:
                # 选一条跨服务的业务事件（不是登录）来还原调用链，演示价值更高。
                row = page.locator("table tbody tr", has_text="command.issue")
                if not row.count():
                    row = page.locator("table tbody tr", has_text="recon_record.submit")
                if not row.count():
                    row = page.locator("table tbody tr")
                row.first.locator("button.link-button").click()
                page.locator(".trace-result").wait_for(timeout=15000)
                page.locator(".trace-result").scroll_into_view_if_needed()
                page.wait_for_timeout(800)
                shot(page, "16-audit-trace")

            step("按请求 ID 还原调用链", trace)

        except Exception:  # noqa: BLE001 - 验收脚本：失败要留证据
            steps.append({"step": "FAILED", "ok": False, "error": traceback.format_exc()[-2000:]})
            shot(page, "99-failure-state")
            print(traceback.format_exc())
        finally:
            context.close()
            browser.close()

    report = {
        "base_url": BASE,
        "steps": steps,
        "console_errors": console_errors[:40],
        "failed_requests": failed_requests[:40],
        "aborted_by_navigation": aborted_requests[:40],
        "ok": all(item.get("ok") for item in steps) and not any(item.get("step") == "FAILED" for item in steps),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告：{REPORT}")
    print(f"控制台错误 {len(console_errors)} 条，请求失败 {len(failed_requests)} 条")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
