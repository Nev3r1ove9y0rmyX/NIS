"""用后端 payload 模型校验演示脚本里的填写内容（不写库、不调接口）。"""

import importlib.util
import pathlib
import sys
import uuid

ROOT = pathlib.Path(r"D:\0study\网络解构\NIS")
sys.path.insert(0, str(ROOT / "services" / "_shared"))


def load(name: str, path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    # 必须先进 sys.modules，否则 pydantic 前向引用（datetime / 同模块模型）解析失败
    sys.modules[name] = module
    spec.loader.exec_module(module)
    for cls_name in dir(module):
        obj = getattr(module, cls_name)
        if hasattr(obj, "model_rebuild"):
            try:
                obj.model_rebuild()
            except Exception:
                pass
    return module


recon = load("recon_payloads", ROOT / "services/recon-service/app/payloads.py")
analysis = load("analysis_payloads", ROOT / "services/analysis-service/app/payloads.py")
decision = load("decision_payloads", ROOT / "services/decision-service/app/payloads.py")

report_id = str(uuid.uuid4())
record_id = str(uuid.uuid4())

recon_content = (
    "在课程授权的演示环境中，观察点位于目标区域北侧路段。连续三日记录显示，每日 08:00 前后有车辆往返通过，"
    "路线固定、间隔稳定；伴随人员上下车与短暂停留（约 5 分钟）。以上内容为演示数据，不对应任何真实目标。"
)

checks = []


def check(name, fn):
    try:
        result = fn()
        checks.append((name, True, result))
        print(f"  [PASS] {name}")
    except Exception as exc:  # noqa: BLE001
        checks.append((name, False, str(exc)))
        print(f"  [FAIL] {name}: {exc}")


print("1) 侦察记录")
check("ReconRecordCreate", lambda: recon.ReconRecordCreate(
    owner_id=str(uuid.uuid4()),
    organization_id=str(uuid.uuid4()),
    title="北侧路段车辆往返观察（08:00 时段）",
    source_type="osint",
    source_ref="演示用公开素材，已脱敏",
    content=recon_content,
    credibility="medium",
    priority="urgent",
    evidence=[],
).model_dump()["title"])

print("\n2) 提交侦察（指派分析员）")
check("ReconSubmit", lambda: recon.ReconSubmit(
    expected_version=1, analyst_ids=[str(uuid.uuid4())]
).model_dump()["analyst_ids"][0][:8])

print("\n3) 分析报告")
check("ReportCreate", lambda: analysis.ReportCreate(
    author_id=str(uuid.uuid4()),
    organization_id=str(uuid.uuid4()),
    title="北侧路段活动规律分析（固定保障节点）",
    recon_record_ids=[record_id],
    key_findings="北侧路段车辆往返时段与路线均稳定，08:00 前后为固定保障节点；人员与车辆在同一时段出现，存在时间耦合。",
    relations="车辆往返与人员上下车在同一时段出现；南北两侧道路的通行情况需要对比确认。",
    risk_level="medium",
    recommended_actions="在固定时段前完成观察点部署，保留影像与通联记录，避免主动接触。",
    priority="normal",
).model_dump()["risk_level"])

print("\n4) 提交报告（指派决策员）")
check("ReportSubmit", lambda: analysis.ReportSubmit(
    expected_version=1, decision_maker_ids=[str(uuid.uuid4())], ai_content_confirmed=True
).model_dump()["ai_content_confirmed"])

print("\n5) 指令")
check("CommandCreate", lambda: decision.CommandCreate(
    decision_maker_id=str(uuid.uuid4()),
    organization_id=str(uuid.uuid4()),
    title="北侧路段核查与反馈（固定时段）",
    objective="确认北侧路段固定时段的车辆往返频次",
    content=(
        "按约定时段到位观察，记录车辆往返频次、停留时长与人员活动；"
        "只做观察与记录，不主动接触；完成后提交结果与证据。"
    ),
    priority="urgent",
    source_report_id=report_id,
).model_dump()["objective"])

print("\n6) 下达指令")
check("CommandIssue", lambda: decision.CommandIssue(
    expected_version=1, executor_ids=[str(uuid.uuid4())], conflict_acknowledged=True
).model_dump()["conflict_acknowledged"])

print("\n7) 执行结果（执行服务 payload）")
execution = load("execution_payloads", ROOT / "services/execution-service/app/payloads.py")
completion = [n for n in dir(execution) if n.endswith("Complete") or "Complete" in n]
print("   可用类：", completion)
for name in completion:
    cls = getattr(execution, name)
    if not hasattr(cls, "model_fields"):
        continue
    fields = cls.model_fields
    if "outcome" in fields and "summary" in fields:
        check(name, lambda cls=cls: cls(
            expected_version=1,
            outcome="success",
            summary="按计划完成北侧路段 08:00 时段观察，取得 2 段连续记录。",
            detail="观察期间记录车辆往返 3 次、人员上下车 2 次；未发生异常接触；影像与通联记录已存档。",
        ).model_dump()["outcome"])

failed = [c for c in checks if not c[1]]
print(f"\n汇总：{len(checks)} 项校验，PASS {len(checks) - len(failed)} / FAIL {len(failed)}")
raise SystemExit(0 if not failed else 1)
