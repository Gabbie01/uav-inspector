"""渲染层测试。"""

from __future__ import annotations

from uav_inspector.models import (
    DeviceKind,
    Finding,
    InspectionReport,
    ReportStatistics,
    Severity,
)
from uav_inspector.render import render_markdown, render_plain


def _report() -> InspectionReport:
    return InspectionReport(
        report_date="2026-10-28",
        site="测试现场",
        overall_status=Severity.HIGH,
        executive_summary="存在一台设备离线。",
        findings=[
            Finding(
                device_id="RF-DET-01",
                device_kind=DeviceKind.RF_DETECT,
                severity=Severity.HIGH,
                title="射频侦测设备离线",
                detail="压制设备离线",
                evidence=["2026-10-28 08:12:03 [RF-DET-01] ERROR 压制设备离线"],
                impact="影响探测连续性",
                recommendation="检查供电与通信链路",
            )
        ],
        immediate_actions=["现场复测 RF-DET-01"],
        follow_up_actions=["提交厂家工单"],
        statistics=ReportStatistics(
            total_lines=51,
            parsed_lines=51,
            unparsed_lines=0,
            devices_total=4,
            affected_devices=1,
            severity_counts={"正常": 0, "轻微": 0, "中等": 1, "严重": 1, "紧急": 0},
            highest_severity=Severity.HIGH,
        ),
    )


class TestRenderMarkdown:
    def test_contains_key_sections(self) -> None:
        text = render_markdown(_report())
        assert "# 反无人机设备巡检报告" in text
        assert "## 一、执行摘要" in text
        assert "## 二、问题明细" in text
        assert "## 三、处置动作" in text

    def test_contains_metadata(self) -> None:
        text = render_markdown(_report())
        assert "测试现场" in text
        assert "2026-10-28" in text
        assert "严重" in text

    def test_contains_evidence_block(self) -> None:
        text = render_markdown(_report())
        assert "```text" in text
        assert "压制设备离线" in text

    def test_actions_rendered(self) -> None:
        text = render_markdown(_report())
        assert "现场复测 RF-DET-01" in text
        assert "提交厂家工单" in text

    def test_empty_findings_message(self) -> None:
        report = _report().model_copy(update={"findings": []})
        text = render_markdown(report)
        assert "本次巡检未发现需要处理的问题" in text

    def test_empty_actions_render_as_none(self) -> None:
        report = _report().model_copy(update={"immediate_actions": [], "follow_up_actions": []})
        text = render_markdown(report)
        assert "当班必须完成" in text
        assert "无" in text


class TestRenderPlain:
    def test_contains_summary_and_findings(self) -> None:
        text = render_plain(_report())
        assert "反无人机设备巡检报告" in text
        assert "【执行摘要】" in text
        assert "【问题明细】" in text
        assert "射频侦测设备离线" in text

    def test_evidence_prefixed(self) -> None:
        text = render_plain(_report())
        assert "> 2026-10-28 08:12:03" in text

    def test_actions_inline(self) -> None:
        text = render_plain(_report())
        assert "当班：现场复测 RF-DET-01" in text
        assert "本周：提交厂家工单" in text
