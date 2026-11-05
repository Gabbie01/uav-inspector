#!/usr/bin/env python3
"""幻觉闸门演示：故意让模型「犯浑」，展示代码层把它拦下来。

这个脚本是给招聘方看的**可复现证据**，不是单元测试。
它做的事情：

1. 读取一份真实形态的巡检日志，用代码解析出真实设备清单；
2. 伪造一段「模型输出」，里面混入四类典型幻觉：
   - 虚构设备编号（日志里根本没有 RF-DET-99）；
   - 伪造证据行（看着像日志，但原文里没有）；
   - 设备类型张冠李戴（把雷达+视觉设备说成激光设备）；
   - 整体状态虚高（模型说「紧急」，但那条紧急依据是虚构设备带来的）；
3. 把这段伪造输出送进真实的事实校验闸门 `validate_findings`；
4. 打印「模型说的」和「闸门之后留下来的」两份结果做对照；
5. 最后跑一遍自检：只要闸门没拦住上面任何一条幻觉，就打印 FAIL 并以非 0 退出。

关键设计：**真实证据行从解析结果里提取，不手写**。
手写字符串很容易在空格、时间戳、标点上和原文差一位（现场日志的级别字段
后面是两个空格），那样演示就变成了「证据对不上→整份被替换」，反而掩盖了
「逐条丢弃伪造行、保留真实行」这个真实行为。

跑法（不需要 API Key，完全离线）：

    uv run python scripts/hallucination_demo.py

退出码恒为 0；只要闸门没拦住上面任何一条幻觉，脚本会打印 FAIL 并以非 0 退出。
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uav_inspector.models import LogRecord, ReportDraft  # noqa: E402
from uav_inspector.parser import parse_log_file  # noqa: E402
from uav_inspector.report import (  # noqa: E402
    build_statistics,
    resolve_overall_status,
    validate_findings,
)

SAMPLE = PROJECT_ROOT / "data" / "samples" / "inspection_2026-10-30-c.log"

RULE = "=" * 72

# 编造的日志行：格式像真的，内容原文里根本没有。
# 用来验证闸门会不会把它们放进最终报告。
FAKE_LASER_EVIDENCE = (
    "2026-10-30 08:51:03 [LASER-01] ERROR  激光发射管温度 480C 超阈值，已损坏"
)
FAKE_RADAR_EVIDENCE = (
    "2026-10-30 11:00:00 [RD-EO-02] ERROR  雷达前端放大器硬件损坏，量程降至 0.3km"
)
FAKE_OFFLINE_EVIDENCE = (
    "2026-10-30 08:50:00 [RF-DET-99] ERROR  设备离线，功放模块烧毁"
)


def pick_real_line(records: list[LogRecord], device_id: str, needle: str) -> str:
    """从解析结果里取出该设备的真实日志行（原文逐字，含原始空格）。

    不手写证据字符串，是这个演示能站得住的前提。
    """
    for record in records:
        if record.device_id == device_id and needle in record.raw:
            return record.raw
    raise LookupError(f"样例日志里找不到 {device_id} 含「{needle}」的行")


def evidence_exists(evidence: str, records: list[LogRecord]) -> bool:
    """与闸门 `_evidence_exists` 同口径：整行相等或被原文包含即算存在。"""
    needle = evidence.strip()
    if not needle:
        return False
    return any(needle == record.raw or needle in record.raw for record in records)


def build_hallucinated_draft(records: list[LogRecord]) -> ReportDraft:
    """伪造一段典型的「模型幻觉」输出。

    内容对应真实大模型实测中出现过的四类问题：
    虚构设备号、伪造证据行、设备类型与等级乱写、整体状态被虚构问题带高。
    """
    # 真实证据：直接从日志解析结果里取，保证逐字一致
    laser_real = pick_real_line(records, "LASER-01", "自检失败")
    radar_real = pick_real_line(records, "RD-EO-01", "慢速回波")

    return ReportDraft.model_validate(
        {
            # 虚高：这个「紧急」完全靠下面那条虚构设备撑起来
            "overall_status": "紧急",
            "executive_summary": "本次巡检共发现 4 项问题，其中 1 项为设备完全离线，"
            "另有 1 台雷达前端异常，建议立即停机检修并联系厂家。",
            "findings": [
                {
                    # 幻觉 1：日志里根本没有这台设备
                    "device_id": "RF-DET-99",
                    "device_kind": "射频信号侦测设备",
                    "severity": "紧急",
                    "title": "射频侦测设备 RF-DET-99 完全离线",
                    "detail": "设备自检连续失败并离线，前端功放已烧毁。",
                    "evidence": [FAKE_OFFLINE_EVIDENCE],
                    "impact": "该频段失去侦测覆盖。",
                    "recommendation": "立即更换射频前端模块。",
                },
                {
                    # 幻觉 2：设备真实存在，证据里混了一条编造的
                    "device_id": "LASER-01",
                    "device_kind": "激光设备",
                    "severity": "严重",
                    "title": "激光测距模块自检失败",
                    "detail": "激光模块自检失败，测距链路完全不可用。",
                    "evidence": [laser_real, FAKE_LASER_EVIDENCE],
                    "impact": "无法为雷达提供激光测距复核。",
                    "recommendation": "现场更换激光测距模块并重新标定。",
                },
                {
                    # 幻觉 3：设备真实存在，但设备类型张冠李戴
                    "device_id": "RD-EO-01",
                    "device_kind": "激光设备",
                    "severity": "中等",
                    "title": "雷达探测到慢速回波，高度 480m",
                    "detail": "500m 高度层检测到慢速回波，高度 480m 方位 32 度，疑似民用旋翼。",
                    "evidence": [radar_real],
                    "impact": "疑似民用旋翼进入低空，可能误联动。",
                    "recommendation": "安排人工复核目标属性。",
                },
                {
                    # 幻觉 4：设备真实存在，但给出的证据整段对不上
                    "device_id": "RD-EO-02",
                    "device_kind": "雷达+视觉设备",
                    "severity": "严重",
                    "title": "雷达前端放大器损坏",
                    "detail": "雷达前端放大器损坏，量程降至 0.3km。",
                    "evidence": [FAKE_RADAR_EVIDENCE],
                    "impact": "探测能力严重下降。",
                    "recommendation": "立即返厂更换前端放大器。",
                },
            ],
            "immediate_actions": ["立即停机检修 RF-DET-99 并更换射频前端模块"],
            "follow_up_actions": ["联系厂家安排激光模块与雷达前端返修"],
        }
    )


def main() -> int:
    records, unparsed = parse_log_file(SAMPLE)
    real_devices = sorted({r.device_id for r in records})
    print(RULE)
    print("uav-inspector · 事实校验闸门演示（离线，不调用任何 API）")
    print(RULE)
    print(f"日志文件   : {SAMPLE.relative_to(PROJECT_ROOT)}")
    print(f"真实解析   : {len(records)} 条记录, {len(unparsed)} 行未解析")
    print(f"真实设备   : {', '.join(real_devices)}")
    print()

    draft = build_hallucinated_draft(records)

    print("-" * 72)
    print("① 模型原始输出（人为注入幻觉）")
    print("-" * 72)
    print(f"整体状态   : {draft.overall_status.value}")
    for finding in draft.findings:
        head = f"  · {finding.device_id:<12} [{finding.device_kind.value}]"
        print(f"{head} {finding.severity.value} — {finding.title}")
        for line in finding.evidence:
            mark = "  " if evidence_exists(line, records) else "✗ "
            print(f"      {mark}{line}")
    print()
    print("  ✗ = 这条证据在原始日志里根本不存在")
    print()

    cleaned, rejected = validate_findings(draft, records)

    print("-" * 72)
    print("② 事实校验闸门处理结果")
    print("-" * 72)
    dropped = len(draft.findings) - len(cleaned)
    print(f"剔除问题项 {dropped} 条 / 保留 {len(cleaned)} 条，拦截说明 {len(rejected)} 条：")
    for message in rejected:
        print(f"  · {message}")
    print()

    print("-" * 72)
    print("③ 闸门之后真正进入报告的问题项")
    print("-" * 72)
    for finding in cleaned:
        head = f"  · {finding.device_id:<12} [{finding.device_kind.value}]"
        print(f"{head} {finding.severity.value} — {finding.title}")
        for line in finding.evidence:
            mark = "✓" if evidence_exists(line, records) else "✗"
            print(f"      {mark} {line}")
    print()

    stats = build_statistics(records, unparsed, cleaned)
    recomputed = resolve_overall_status(draft.overall_status, cleaned)

    print("-" * 72)
    print("④ 客观统计与整体状态（全部由代码重算，不采信模型给的数字）")
    print("-" * 72)
    print(f"模型声称整体状态 : {draft.overall_status.value}")
    print(f"代码重算整体状态 : {recomputed.value}")
    print(
        f"日志行数         : 总 {stats.total_lines} / 可解析 {stats.parsed_lines}"
        f" / 未解析 {stats.unparsed_lines}"
    )
    print(
        f"设备数           : 覆盖 {stats.devices_total} 台"
        f" / 存在问题 {stats.affected_devices} 台"
    )
    print(f"问题分级         : {stats.severity_counts}")
    print()

    # ---- 自检：闸门必须拦下上面所有幻觉 ----
    print("-" * 72)
    print("⑤ 闸门自检")
    print("-" * 72)
    checks: list[tuple[str, bool]] = []

    kept_devices = {f.device_id for f in cleaned}
    checks.append(("虚构设备 RF-DET-99 被剔除", "RF-DET-99" not in kept_devices))

    all_evidence = [line for f in cleaned for line in f.evidence]
    checks.append(("伪造证据行被剔除", FAKE_LASER_EVIDENCE not in all_evidence))
    checks.append(("伪造的雷达证据被剔除", FAKE_RADAR_EVIDENCE not in all_evidence))
    checks.append(
        (
            "真实证据行被逐条保留（没被整份替换掉）",
            any(evidence_exists(e, records) for e in all_evidence),
        )
    )
    checks.append(
        (
            "所有留存证据都能在原始日志中逐字匹配",
            all(evidence_exists(line, records) for line in all_evidence),
        )
    )

    rd_eo_01 = next((f for f in cleaned if f.device_id == "RD-EO-01"), None)
    checks.append(
        (
            "RD-EO-01 的设备类型被纠正回真实值",
            rd_eo_01 is not None and rd_eo_01.device_kind.value == "雷达+视觉设备",
        )
    )

    rd_eo_02 = next((f for f in cleaned if f.device_id == "RD-EO-02"), None)
    checks.append(
        (
            "RD-EO-02 的编造证据被替换为真实日志行",
            rd_eo_02 is not None
            and bool(rd_eo_02.evidence)
            and all(evidence_exists(line, records) for line in rd_eo_02.evidence),
        )
    )

    checks.append(
        (
            "整体状态按清洗后问题项重算，未沿用模型虚高值",
            recomputed is not draft.overall_status,
        )
    )
    checks.append(
        (
            "严重度统计由代码重算，与清洗后问题项一致",
            sum(stats.severity_counts.values()) == len(cleaned),
        )
    )

    failed = 0
    for name, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"结果：{failed} 项自检未通过 —— 闸门存在漏洞！")
        return 1
    print("结果：全部自检通过 —— 模型幻觉被完整拦截，报告只保留可追溯的事实。")
    print(RULE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
