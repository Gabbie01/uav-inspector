"""数据模型与 schema 校验测试。

重点验证：模型输出不合法时，schema 能否把它挡下来或容错住。
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from uav_inspector.models import (
    DeviceKind,
    Finding,
    ReportDraft,
    Severity,
)


class TestSeverityCoerce:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("正常", Severity.NORMAL),
            ("轻微", Severity.LOW),
            ("中等", Severity.MEDIUM),
            ("严重", Severity.HIGH),
            ("紧急", Severity.CRITICAL),
            ("HIGH", Severity.HIGH),
            ("high", Severity.HIGH),
            ("critical", Severity.CRITICAL),
            ("ok", Severity.NORMAL),
            ("major", Severity.HIGH),
        ],
    )
    def test_known_values(self, raw: str, expected: Severity) -> None:
        assert Severity.coerce(raw) is expected

    def test_unknown_raises(self) -> None:
        with pytest.raises(ValueError):
            Severity.coerce("灾难级")

    def test_rank_ordering(self) -> None:
        assert Severity.NORMAL.rank < Severity.LOW.rank < Severity.MEDIUM.rank
        assert Severity.MEDIUM.rank < Severity.HIGH.rank < Severity.CRITICAL.rank


class TestFindingCoercion:
    def test_english_severity_accepted(self) -> None:
        finding = Finding(device_id="A-1", severity="HIGH", title="t", detail="d")  # type: ignore[arg-type]
        assert finding.severity is Severity.HIGH

    def test_garbage_severity_falls_back_to_medium(self) -> None:
        finding = Finding(device_id="A-1", severity="???", title="t", detail="d")  # type: ignore[arg-type]
        assert finding.severity is Severity.MEDIUM

    def test_none_severity_falls_back_to_medium(self) -> None:
        finding = Finding(device_id="A-1", severity=None, title="t", detail="d")  # type: ignore[arg-type]
        assert finding.severity is Severity.MEDIUM

    def test_english_device_kind_accepted(self) -> None:
        finding = Finding(device_id="A-1", device_kind="RF_JAM", title="t", detail="d")  # type: ignore[arg-type]
        assert finding.device_kind is DeviceKind.RF_JAM

    def test_partial_device_kind_accepted(self) -> None:
        finding = Finding(device_id="A-1", device_kind="无线电电压制", title="t", detail="d")  # type: ignore[arg-type]
        assert finding.device_kind is DeviceKind.RF_JAM

    def test_garbage_device_kind_falls_back_to_unknown(self) -> None:
        finding = Finding(device_id="A-1", device_kind="外星设备", title="t", detail="d")  # type: ignore[arg-type]
        assert finding.device_kind is DeviceKind.UNKNOWN

    def test_empty_device_kind_falls_back_to_unknown(self) -> None:
        finding = Finding(device_id="A-1", device_kind="", title="t", detail="d")  # type: ignore[arg-type]
        assert finding.device_kind is DeviceKind.UNKNOWN


class TestReportDraft:
    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValidationError):
            ReportDraft.model_validate(
                {
                    "overall_status": "正常",
                    "executive_summary": "x",
                    "findings": [],
                    "unexpected_field": 1,
                }
            )

    def test_requires_executive_summary(self) -> None:
        with pytest.raises(ValidationError):
            ReportDraft.model_validate({"overall_status": "正常"})

    def test_severity_alias_coerced(self) -> None:
        draft = ReportDraft.model_validate(
            {"overall_status": "CRITICAL", "executive_summary": "x", "findings": []}
        )
        assert draft.overall_status is Severity.CRITICAL

    def test_findings_sorted_by_severity(self) -> None:
        draft = ReportDraft.model_validate(
            {
                "overall_status": "严重",
                "executive_summary": "x",
                "findings": [
                    {"device_id": "B", "severity": "轻微", "title": "t1", "detail": "d"},
                    {"device_id": "A", "severity": "紧急", "title": "t2", "detail": "d"},
                    {"device_id": "C", "severity": "中等", "title": "t3", "detail": "d"},
                ],
            }
        )
        assert [f.device_id for f in draft.findings] == ["A", "C", "B"]

    def test_title_length_limit(self) -> None:
        with pytest.raises(ValidationError):
            ReportDraft.model_validate(
                {
                    "overall_status": "正常",
                    "executive_summary": "x",
                    "findings": [
                        {"device_id": "A", "title": "x" * 61, "detail": "d"},
                    ],
                }
            )
