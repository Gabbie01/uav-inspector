"""报告编排与事实校验测试。

这一组测试是整个项目的价值核心：验证模型即使编造内容，
也污染不到最终交付的报告。
"""

from __future__ import annotations

import json

from uav_inspector.models import DeviceKind, LogRecord, ReportDraft, Severity
from uav_inspector.report import (
    build_statistics,
    generate_report,
    severity_prior_table,
    validate_findings,
)


class StubLLM:
    """返回固定 JSON 的假客户端。"""

    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = json.dumps(payload, ensure_ascii=False)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self._payload


def _records() -> list[LogRecord]:
    return [
        LogRecord(
            timestamp="2026-10-28 08:12:03",
            device_id="RF-DET-01",
            device_kind=DeviceKind.RF_DETECT,
            level="ERROR",
            message="压制设备离线，前端面板显示无信号",
            raw="2026-10-28 08:12:03 [RF-DET-01] ERROR 压制设备离线，前端面板显示无信号",
        ),
        LogRecord(
            timestamp="2026-10-28 08:13:10",
            device_id="RD-EO-01",
            device_kind=DeviceKind.RADAR_EO,
            level="INFO",
            message="雷达自检通过",
            raw="2026-10-28 08:13:10 [RD-EO-01] INFO 雷达自检通过",
        ),
    ]


def _draft(**overrides: object) -> ReportDraft:
    payload: dict[str, object] = {
        "overall_status": "紧急",
        "executive_summary": "共发现若干问题。",
        "findings": [],
        "immediate_actions": [],
        "follow_up_actions": [],
    }
    payload.update(overrides)
    return ReportDraft.model_validate(payload)


class TestValidateFindings:
    def test_hallucinated_device_is_rejected(self) -> None:
        draft = _draft(
            findings=[
                {
                    "device_id": "RF-DET-99",
                    "severity": "紧急",
                    "title": "不存在的设备",
                    "detail": "模型编造的设备",
                    "evidence": [],
                }
            ]
        )
        cleaned, rejected = validate_findings(draft, _records())
        assert cleaned == []
        assert len(rejected) == 1
        assert "RF-DET-99" in rejected[0]
        assert "虚构" in rejected[0]

    def test_fabricated_evidence_is_replaced_with_real_log(self) -> None:
        draft = _draft(
            findings=[
                {
                    "device_id": "RF-DET-01",
                    "severity": "紧急",
                    "title": "设备离线",
                    "detail": "设备离线",
                    "evidence": ["2026-01-01 00:00:00 [RF-DET-01] ERROR 这行日志根本不存在"],
                }
            ]
        )
        cleaned, rejected = validate_findings(draft, _records())
        assert len(cleaned) == 1
        assert cleaned[0].evidence == [
            "2026-10-28 08:12:03 [RF-DET-01] ERROR 压制设备离线，前端面板显示无信号"
        ]
        assert rejected and "替换" in rejected[0]

    def test_valid_evidence_is_preserved(self) -> None:
        real_line = "2026-10-28 08:12:03 [RF-DET-01] ERROR 压制设备离线，前端面板显示无信号"
        draft = _draft(
            findings=[
                {
                    "device_id": "RF-DET-01",
                    "severity": "紧急",
                    "title": "设备离线",
                    "detail": "设备离线",
                    "evidence": [real_line],
                }
            ]
        )
        cleaned, rejected = validate_findings(draft, _records())
        assert cleaned[0].evidence == [real_line]
        assert rejected == []

    def test_wrong_device_kind_is_corrected(self) -> None:
        draft = _draft(
            findings=[
                {
                    "device_id": "RF-DET-01",
                    "device_kind": "激光设备",
                    "severity": "紧急",
                    "title": "设备离线",
                    "detail": "设备离线",
                    "evidence": [],
                }
            ]
        )
        cleaned, _ = validate_findings(draft, _records())
        assert cleaned[0].device_kind is DeviceKind.RF_DETECT

    def test_findings_sorted_by_severity(self) -> None:
        draft = _draft(
            findings=[
                {
                    "device_id": "RF-DET-01",
                    "severity": "轻微",
                    "title": "a",
                    "detail": "d",
                    "evidence": [],
                },
                {
                    "device_id": "RD-EO-01",
                    "severity": "紧急",
                    "title": "b",
                    "detail": "d",
                    "evidence": [],
                },
            ]
        )
        cleaned, _ = validate_findings(draft, _records())
        assert [f.severity for f in cleaned] == [Severity.CRITICAL, Severity.LOW]


class TestBuildStatistics:
    def test_counts_from_cleaned_findings(self) -> None:
        findings = [
            _draft(
                findings=[
                    {
                        "device_id": "RF-DET-01",
                        "severity": "紧急",
                        "title": "a",
                        "detail": "d",
                        "evidence": [],
                    }
                ]
            ).findings[0]
        ]
        stats = build_statistics(_records(), [], findings)
        assert stats.parsed_lines == 2
        assert stats.devices_total == 2
        assert stats.affected_devices == 1
        assert stats.highest_severity is Severity.CRITICAL
        assert stats.severity_counts["紧急"] == 1

    def test_unparsed_lines_counted(self) -> None:
        stats = build_statistics(_records(), ["坏行1", "坏行2"], [])
        assert stats.total_lines == 4
        assert stats.unparsed_lines == 2

    def test_all_severity_buckets_present(self) -> None:
        stats = build_statistics(_records(), [], [])
        for severity in Severity:
            assert severity.value in stats.severity_counts


class TestGenerateReport:
    def test_end_to_end_with_stub(self) -> None:
        client = StubLLM(
            {
                "overall_status": "紧急",
                "executive_summary": "RF-DET-01 离线。",
                "findings": [
                    {
                        "device_id": "RF-DET-01",
                        "device_kind": "射频信号侦测设备",
                        "severity": "紧急",
                        "title": "设备离线",
                        "detail": "压制设备离线",
                        "evidence": [],
                        "impact": "影响探测连续性",
                        "recommendation": "检查供电",
                    }
                ],
                "immediate_actions": ["现场复测"],
                "follow_up_actions": ["提交工单"],
            }
        )
        log = (
            "2026-10-28 08:12:03 [RF-DET-01] ERROR 压制设备离线，前端面板显示无信号\n"
            "2026-10-28 08:13:10 [RD-EO-01] INFO 雷达自检通过\n"
        )
        report = generate_report(client, log, site="测试现场", report_date="2026-10-28")
        assert report.site == "测试现场"
        assert report.report_date == "2026-10-28"
        assert len(report.findings) == 1
        assert report.statistics.affected_devices == 1

    def test_data_quality_note_added_when_rejected(self) -> None:
        client = StubLLM(
            {
                "overall_status": "紧急",
                "executive_summary": "摘要。",
                "findings": [
                    {
                        "device_id": "FAKE-01",
                        "severity": "紧急",
                        "title": "虚构设备",
                        "detail": "d",
                        "evidence": [],
                    }
                ],
                "immediate_actions": [],
                "follow_up_actions": [],
            }
        )
        log = "2026-10-28 08:12:03 [RD-EO-01] INFO 雷达自检通过"
        report = generate_report(client, log, site="测试")
        assert "数据质量提示" in report.executive_summary
        assert report.findings == []
        # 关键：统计必须与清洗后的问题数一致
        assert report.statistics.severity_counts["紧急"] == 0
        assert report.statistics.highest_severity is Severity.NORMAL

    def test_empty_log_raises(self) -> None:
        client = StubLLM({})
        try:
            generate_report(client, "这不是日志", site="测试")
        except ValueError as exc:
            assert "未能从输入中解析出任何巡检记录" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("应当抛出 ValueError")

    def test_unparsed_lines_surfaced_in_statistics(self) -> None:
        client = StubLLM(
            {
                "overall_status": "正常",
                "executive_summary": "ok",
                "findings": [],
                "immediate_actions": [],
                "follow_up_actions": [],
            }
        )
        log = "2026-10-28 08:12:03 [RD-EO-01] INFO 正常\n这一行无法解析\n"
        report = generate_report(client, log, site="测试")
        assert report.statistics.unparsed_lines == 1


class TestSeverityPriorTable:
    def test_sorted_by_severity_desc(self, records: list[LogRecord]) -> None:
        table = severity_prior_table(records)
        ranks = [severity.rank for _, severity in table]
        assert ranks == sorted(ranks, reverse=True)

    def test_covers_all_devices(self, records: list[LogRecord]) -> None:
        table = severity_prior_table(records)
        assert len(table) == len({r.device_id for r in records})
