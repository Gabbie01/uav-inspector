#!/usr/bin/env python3
"""独立校验 docs/examples/ 下的真实报告是否守住了事实。

这个脚本不信任生成报告的流水线，也不信任闸门自己，
而是拿「原始日志」当唯一真相，回查报告里的每一条证据：

1. 报告里出现的每个设备编号，必须在原始日志里真实存在；
2. 报告里引用的每一条证据行，必须能在原始日志中逐字找到；
3. 报告头部声明的分级数量，必须等于报告里问题项的实际条数；
4. 报告声明的「可解析 / 未解析 / 覆盖设备数」，必须等于代码重新解析日志的结果。

任何一条对不上就以非 0 退出，可以直接当 CI 闸门用。

跑法（不需要 API Key，完全离线）：

    uv run python scripts/verify_examples.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from uav_inspector.parser import parse_log_file  # noqa: E402

EXAMPLES_DIR = PROJECT_ROOT / "docs" / "examples"

# 报告 <-> 日志 的对应关系（文件名后缀一致）
LOG_SUFFIX_TO_REPORT = {
    "2026-10-28": "report_2026-10-28.md",
    "2026-10-29-b": "report_2026-10-29-b.md",
    "2026-10-30-c": "report_2026-10-30-c.md",
}

# 报告正文里「原始记录」代码块中的日志行
EVIDENCE_LINE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} \[[A-Z0-9-]+\]")

# 报告头部「日志统计」一行
STAT_RE = re.compile(
    r"共 (\d+) 行，可解析 (\d+) 行，未解析 (\d+) 行，覆盖 (\d+) 台设备，其中 (\d+) 台存在问题"
)
# 报告头部「问题分级」一行
SEVERITY_RE = re.compile(r"问题分级\*\*：(.+?)（最高")

# 「### N. [等级] 标题（设备号）」形式的问题项标题
FINDING_TITLE_RE = re.compile(r"^### \d+\. \[(.+?)\] .+?（([A-Z0-9-]+)）\s*$", re.MULTILINE)

SEVERITY_ORDER = ["紧急", "严重", "中等", "轻微"]


def extract_evidence_lines(report_text: str) -> list[str]:
    """抽出报告里所有被当作证据引用的日志行（原文逐字）。"""
    lines: list[str] = []
    in_block = False
    for raw in report_text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("```"):
            in_block = not in_block
            continue
        if in_block and EVIDENCE_LINE_RE.match(stripped):
            lines.append(stripped)
    return lines


def parse_severity_counts(segment: str) -> dict[str, int]:
    """解析「严重 2，中等 2，轻微 3」这种统计串。"""
    counts: dict[str, int] = {}
    for severity in SEVERITY_ORDER:
        match = re.search(rf"{severity}\s*(\d+)", segment)
        if match:
            counts[severity] = int(match.group(1))
    return counts


def verify_one(log_suffix: str, report_name: str) -> list[str]:
    """校验一份报告，返回问题列表（空列表表示通过）。"""
    problems: list[str] = []
    log_path = PROJECT_ROOT / "data" / "samples" / f"inspection_{log_suffix}.log"
    report_path = EXAMPLES_DIR / report_name

    if not log_path.exists():
        return [f"缺少原始日志：{log_path.relative_to(PROJECT_ROOT)}"]
    if not report_path.exists():
        return [f"缺少报告：{report_path.relative_to(PROJECT_ROOT)}"]

    records, unparsed = parse_log_file(log_path)
    raw_lines = {r.raw for r in records}
    real_devices = {r.device_id for r in records}
    report_text = report_path.read_text(encoding="utf-8")

    # --- 1. 设备编号必须真实存在 ---
    for device_id in sorted({m.group(1) for m in EVIDENCE_LINE_RE.finditer(report_text)}):
        if device_id not in real_devices:
            problems.append(f"报告引用了日志中不存在的设备：{device_id}")

    finding_titles = FINDING_TITLE_RE.findall(report_text)
    for _severity, device_id in finding_titles:
        if device_id not in real_devices:
            problems.append(f"问题项引用了日志中不存在的设备：{device_id}")

    # --- 2. 每条证据行必须能在原始日志中逐字找到 ---
    evidence = extract_evidence_lines(report_text)
    if not evidence:
        problems.append("报告里没有找到任何证据行")
    for line in evidence:
        if line not in raw_lines:
            problems.append(f"证据行无法在原始日志中逐字匹配：{line}")

    # --- 3. 问题项条数必须与分级统计一致 ---
    stat_match = STAT_RE.search(report_text)
    severity_match = SEVERITY_RE.search(report_text)
    if stat_match is None:
        problems.append("报告头部缺少可解析的「日志统计」行")
    if severity_match is None:
        problems.append("报告头部缺少可解析的「问题分级」行")

    if stat_match and severity_match:
        total_lines = int(stat_match.group(1))
        parsed_lines = int(stat_match.group(2))
        unparsed_lines = int(stat_match.group(3))
        devices_total = int(stat_match.group(4))
        devices_affected = int(stat_match.group(5))

        declared = parse_severity_counts(severity_match.group(1))
        declared_total = sum(declared.values())
        actual_findings = len(finding_titles)
        if declared_total != actual_findings:
            problems.append(
                f"分级统计合计 {declared_total}，但报告里实际有 {actual_findings} 个问题项"
            )

        # --- 4. 头部统计必须等于代码重新解析的结果 ---
        real_total = len(records) + len(unparsed)
        if total_lines != real_total:
            problems.append(f"声明总行数 {total_lines}，实际 {real_total}")
        if parsed_lines != len(records):
            problems.append(f"声明可解析 {parsed_lines}，实际 {len(records)}")
        if unparsed_lines != len(unparsed):
            problems.append(f"声明未解析 {unparsed_lines}，实际 {len(unparsed)}")
        if devices_total != len(real_devices):
            problems.append(f"声明覆盖 {devices_total} 台设备，实际 {len(real_devices)}")
        affected = {device_id for _s, device_id in finding_titles}
        if devices_affected != len(affected):
            problems.append(
                f"声明 {devices_affected} 台设备存在问题，实际 {len(affected)} 台"
            )

    return problems


def main() -> int:
    print("=" * 72)
    print("uav-inspector · 真实报告事实校验（离线，不调用任何 API）")
    print("=" * 72)
    print(f"报告目录   : {EXAMPLES_DIR.relative_to(PROJECT_ROOT)}")
    print()

    total_problems = 0
    for log_suffix, report_name in LOG_SUFFIX_TO_REPORT.items():
        problems = verify_one(log_suffix, report_name)
        status = "PASS" if not problems else "FAIL"
        print(f"[{status}] {report_name}")
        if problems:
            total_problems += len(problems)
            for item in problems:
                print(f"       - {item}")
        else:
            print("       证据行、设备编号、分级统计、头部统计全部与原始日志一致")
    print()

    if total_problems:
        print(f"结果：{total_problems} 处不一致 —— 报告存在事实问题！")
        return 1
    print(f"结果：{len(LOG_SUFFIX_TO_REPORT)} 份真实报告全部通过事实校验。")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
