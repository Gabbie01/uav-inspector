"""多场景样例日志测试。

背景：仓库里现在有三份真实形态的巡检日志，分别对应三类现场：

    inspection_2026-10-28.log   基础样例（引入时的那一份）
    inspection_2026-10-29-b.log  射频侦测 + 无线电电压制 + 激光
    inspection_2026-10-30-c.log  雷达 + 视觉 + 激光，且**故意含 2 行格式异常**

第三份是刻意设计的：现场日志不是每一行都规规矩矩，
解析器必须把坏行单独收集起来如实上报，而不是丢掉或让整份日志解析失败。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uav_inspector.models import DeviceKind, Severity
from uav_inspector.parser import estimate_severity, parse_log_file
from uav_inspector.report import build_statistics, severity_prior_table

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLES_DIR = PROJECT_ROOT / "data" / "samples"

SAMPLE_FILES = (
    "inspection_2026-10-28.log",
    "inspection_2026-10-29-b.log",
    "inspection_2026-10-30-c.log",
)


@pytest.fixture(params=SAMPLE_FILES)
def sample_file(request: pytest.FixtureRequest) -> Path:
    path = SAMPLES_DIR / request.param
    if not path.exists():
        pytest.skip(f"样例日志缺失：{path}")
    return path


class TestAllSamplesParse:
    def test_every_sample_yields_records(self, sample_file: Path) -> None:
        records, _ = parse_log_file(sample_file)
        assert len(records) > 0

    def test_every_sample_device_id_is_resolvable(self, sample_file: Path) -> None:
        """所有设备编号都要能映射到已知设备类型，不允许出现 UNKNOWN。"""
        records, _ = parse_log_file(sample_file)
        kinds = {r.device_kind for r in records}
        assert DeviceKind.UNKNOWN not in kinds


class TestMalformedLineSample:
    """针对 inspection_2026-10-30-c.log：格式异常行必须被单独收集而不是丢弃。"""

    @pytest.fixture
    def c_sample(self) -> Path:
        path = SAMPLES_DIR / "inspection_2026-10-30-c.log"
        if not path.exists():
            pytest.skip(f"样例日志缺失：{path}")
        return path

    def test_exactly_two_unparsed_lines(self, c_sample: Path) -> None:
        records, unparsed = parse_log_file(c_sample)
        assert len(unparsed) == 2

    def test_unparsed_lines_are_preserved_verbatim(self, c_sample: Path) -> None:
        _, unparsed = parse_log_file(c_sample)
        # 缺少方括号 + 未知级别 NOTICE，两种典型的现场手写/导出脏数据
        assert any("14:02:11" in line and "[" not in line for line in unparsed)
        assert any("NOTICE" in line for line in unparsed)

    def test_malformed_lines_do_not_abort_parsing(self, c_sample: Path) -> None:
        """坏行不能让整份日志解析失败——可用记录仍应完整产出。"""
        records, unparsed = parse_log_file(c_sample)
        assert len(records) == 34
        assert len(unparsed) == 2

    def test_statistics_report_unparsed_count(self, c_sample: Path) -> None:
        records, unparsed = parse_log_file(c_sample)
        stats = build_statistics(records, unparsed, [])
        assert stats.unparsed_lines == 2
        assert stats.parsed_lines == 34
        assert stats.total_lines == 36


class TestSeverityPriorTable:
    def test_ranks_devices_by_severity(self, sample_file: Path) -> None:
        records, _ = parse_log_file(sample_file)
        table = severity_prior_table(records)
        ranks = [severity.rank for _, severity in table]
        assert ranks == sorted(ranks, reverse=True)

    def test_detects_offline_device_as_critical(self, sample_file: Path) -> None:
        """「设备离线」必须被关键词表判为紧急，这是现场最需要立刻处理的情况。"""
        records, _ = parse_log_file(sample_file)
        offline = [r for r in records if "离线" in r.message]
        if not offline:
            pytest.skip("该样例不含离线事件")
        assert estimate_severity(offline[0]) is Severity.CRITICAL


class TestSampleCoverage:
    def test_all_four_device_kinds_covered_across_samples(self) -> None:
        """三份样例合起来要覆盖全部四类设备。"""
        kinds: set[DeviceKind] = set()
        for name in SAMPLE_FILES:
            path = SAMPLES_DIR / name
            if not path.exists():
                continue
            records, _ = parse_log_file(path)
            kinds.update(r.device_kind for r in records)
        assert kinds >= {
            DeviceKind.RF_DETECT,
            DeviceKind.RF_JAM,
            DeviceKind.RADAR_EO,
            DeviceKind.LASER,
        }
