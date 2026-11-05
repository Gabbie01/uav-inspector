"""日志解析器测试：纯确定性逻辑，不涉及模型。"""

from __future__ import annotations

from pathlib import Path

from uav_inspector.models import DeviceKind, LogRecord, Severity
from uav_inspector.parser import (
    device_kind_of,
    estimate_severity,
    parse_log_file,
    parse_log_text,
)


class TestDeviceKind:
    def test_prefix_mapping(self) -> None:
        assert device_kind_of("RF-JAM-01") is DeviceKind.RF_JAM
        assert device_kind_of("RF-DET-02") is DeviceKind.RF_DETECT
        assert device_kind_of("RD-EO-01") is DeviceKind.RADAR_EO
        assert device_kind_of("LASER-01") is DeviceKind.LASER

    def test_case_insensitive(self) -> None:
        assert device_kind_of("rf-det-01") is DeviceKind.RF_DETECT

    def test_unknown_prefix(self) -> None:
        assert device_kind_of("XYZ-99") is DeviceKind.UNKNOWN

    def test_single_segment_id(self) -> None:
        assert device_kind_of("LASER") is DeviceKind.LASER


class TestParseLogText:
    def test_parses_all_sample_lines(self, sample_log_text: str) -> None:
        records, unparsed = parse_log_text(sample_log_text)
        assert len(records) == 51
        assert unparsed == []

    def test_record_fields(self) -> None:
        text = "2026-10-28 08:12:03 [RF-DET-01] INFO  射频侦测设备自检通过"
        records, unparsed = parse_log_text(text)
        assert unparsed == []
        record = records[0]
        assert record.timestamp == "2026-10-28 08:12:03"
        assert record.device_id == "RF-DET-01"
        assert record.device_kind is DeviceKind.RF_DETECT
        assert record.level == "INFO"
        assert record.message == "射频侦测设备自检通过"

    def test_blank_lines_skipped(self) -> None:
        records, unparsed = parse_log_text("\n\n   \n2026-10-28 08:12:03 [A-1] INFO  ok\n")
        assert len(records) == 1
        assert unparsed == []

    def test_malformed_line_collected_as_unparsed(self) -> None:
        text = "2026-10-28 08:12:03 [RF-DET-01] INFO  正常行\n这是一行完全不符合格式的日志\n"
        records, unparsed = parse_log_text(text)
        assert len(records) == 1
        assert len(unparsed) == 1
        assert "不符合格式" in unparsed[0]

    def test_warning_level_normalised(self) -> None:
        records, _ = parse_log_text("2026-10-28 08:12:03 [A-1] WARNING  x")
        assert records[0].level == "WARNING"

    def test_empty_input(self) -> None:
        records, unparsed = parse_log_text("")
        assert records == []
        assert unparsed == []


class TestParseLogFile:
    def test_reads_sample(self, sample_log_path: Path) -> None:
        records, unparsed = parse_log_file(sample_log_path)
        assert len(records) == 51
        assert unparsed == []


class TestEstimateSeverity:
    def _record(self, level: str, message: str) -> LogRecord:
        return LogRecord(
            timestamp="2026-10-28 08:12:03",
            device_id="RF-DET-01",
            device_kind=DeviceKind.RF_DETECT,
            level=level,
            message=message,
            raw="raw",
        )

    def test_info_normal(self) -> None:
        assert estimate_severity(self._record("INFO", "频段扫描正常")) is Severity.NORMAL

    def test_error_high(self) -> None:
        assert estimate_severity(self._record("ERROR", "something broke")) is Severity.HIGH

    def test_critical_level(self) -> None:
        assert estimate_severity(self._record("CRITICAL", "x")) is Severity.CRITICAL

    def test_keyword_overrides_lower_level(self) -> None:
        # INFO 但含"离线"关键词 -> 紧急
        assert estimate_severity(self._record("INFO", "设备离线")) is Severity.CRITICAL

    def test_keyword_raises_level(self) -> None:
        # WARN 但含"故障" -> 严重
        assert estimate_severity(self._record("WARN", "模块故障")) is Severity.HIGH

    def test_most_severe_keyword_wins(self) -> None:
        assert estimate_severity(self._record("WARN", "告警后设备离线")) is Severity.CRITICAL
