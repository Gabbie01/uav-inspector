"""报告渲染：把 InspectionReport 输出为 Markdown / 纯文本。"""

from __future__ import annotations

from .models import InspectionReport, Severity

_SEVERITY_ICON: dict[Severity, str] = {
    Severity.CRITICAL: "[紧急]",
    Severity.HIGH: "[严重]",
    Severity.MEDIUM: "[中等]",
    Severity.LOW: "[轻微]",
    Severity.NORMAL: "[正常]",
}


def render_markdown(report: InspectionReport) -> str:
    """渲染为 Markdown。"""
    stats = report.statistics
    lines: list[str] = []

    lines.append("# 反无人机设备巡检报告")
    lines.append("")
    lines.append(f"- **现场**：{report.site}")
    lines.append(f"- **报告日期**：{report.report_date}")
    lines.append(
        f"- **整体状态**：{_SEVERITY_ICON[report.overall_status]} {report.overall_status.value}"
    )
    lines.append(
        f"- **日志统计**：共 {stats.total_lines} 行，可解析 {stats.parsed_lines} 行，"
        f"未解析 {stats.unparsed_lines} 行，覆盖 {stats.devices_total} 台设备，"
        f"其中 {stats.affected_devices} 台存在问题"
    )
    severity_text = "，".join(f"{k} {v}" for k, v in stats.severity_counts.items() if v > 0) or "无"
    lines.append(f"- **问题分级**：{severity_text}（最高 {stats.highest_severity.value}）")
    lines.append("")

    lines.append("## 一、执行摘要")
    lines.append("")
    lines.append(report.executive_summary)
    lines.append("")

    lines.append("## 二、问题明细")
    lines.append("")
    if not report.findings:
        lines.append("本次巡检未发现需要处理的问题。")
        lines.append("")
    else:
        for index, finding in enumerate(report.findings, start=1):
            lines.append(
                f"### {index}. {_SEVERITY_ICON[finding.severity]} {finding.title}"
                f"（{finding.device_id}）"
            )
            lines.append("")
            lines.append(f"- **设备类型**：{finding.device_kind.value}")
            lines.append(f"- **风险等级**：{finding.severity.value}")
            lines.append(f"- **现象与判断**：{finding.detail}")
            if finding.impact:
                lines.append(f"- **影响**：{finding.impact}")
            if finding.recommendation:
                lines.append(f"- **处置建议**：{finding.recommendation}")
            if finding.evidence:
                lines.append("- **原始记录**：")
                lines.append("")
                lines.append("  ```text")
                for line in finding.evidence:
                    lines.append(f"  {line}")
                lines.append("  ```")
            lines.append("")

    lines.append("## 三、处置动作")
    lines.append("")
    lines.append("### 当班必须完成")
    lines.append("")
    if report.immediate_actions:
        lines.extend(f"{i}. {action}" for i, action in enumerate(report.immediate_actions, 1))
    else:
        lines.append("无")
    lines.append("")
    lines.append("### 本周内闭环")
    lines.append("")
    if report.follow_up_actions:
        lines.extend(f"{i}. {action}" for i, action in enumerate(report.follow_up_actions, 1))
    else:
        lines.append("无")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append(
        "*本报告由 uav-inspector 自动生成：日志解析、统计与校验由代码完成，"
        "风险定级、故障归因与处置建议由大模型生成，并经事实校验。*"
    )
    return "\n".join(lines)


def render_plain(report: InspectionReport) -> str:
    """渲染为纯文本（适合贴进邮件或工单）。"""
    stats = report.statistics
    lines: list[str] = []
    lines.append("反无人机设备巡检报告")
    lines.append("=" * 40)
    lines.append(f"现场：{report.site}")
    lines.append(f"日期：{report.report_date}")
    lines.append(f"整体状态：{report.overall_status.value}")
    lines.append(
        f"日志：{stats.total_lines} 行"
        f"（可解析 {stats.parsed_lines}，未解析 {stats.unparsed_lines}）"
    )
    lines.append("")
    lines.append("【执行摘要】")
    lines.append(report.executive_summary)
    lines.append("")
    lines.append("【问题明细】")
    if not report.findings:
        lines.append("  未发现需要处理的问题。")
    for index, finding in enumerate(report.findings, start=1):
        lines.append(
            f"  {index}. [{finding.severity.value}] {finding.title}（{finding.device_id}）"
        )
        lines.append(f"     {finding.detail}")
        if finding.recommendation:
            lines.append(f"     建议：{finding.recommendation}")
        for line in finding.evidence:
            lines.append(f"     > {line}")
    lines.append("")
    lines.append("【处置动作】")
    lines.append("  当班：" + ("；".join(report.immediate_actions) or "无"))
    lines.append("  本周：" + ("；".join(report.follow_up_actions) or "无"))
    return "\n".join(lines)
