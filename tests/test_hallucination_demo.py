"""幻觉闸门演示脚本的回归测试。

背景：`scripts/hallucination_demo.py` 是给招聘方看的可复现证据，
脚本内部有 9 条 PASS/FAIL 自检。但脚本本身不在 pytest 覆盖范围内，
改动 report.py 或脚本时可能悄悄把自检搞挂。

所以这里把脚本的核心行为搬进 pytest：
    - 脚本能正常跑完且退出码为 0（自检全过）
    - 四类幻觉确实被闸门拦住
    - 真实证据行不会被整份替换掉（逐条丢弃，而不是一刀切）

这些用例与 scripts/hallucination_demo.py 里的自检是同一套判据，
两边同时跑，任何一边失效都会红。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from uav_inspector.parser import parse_log_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEMO_SCRIPT = PROJECT_ROOT / "scripts" / "hallucination_demo.py"
SAMPLE = PROJECT_ROOT / "data" / "samples" / "inspection_2026-10-30-c.log"


@pytest.fixture(scope="module")
def demo_module() -> ModuleType:
    """按文件路径加载演示脚本（scripts/ 不是包，不能直接 import）。"""
    if not DEMO_SCRIPT.exists():
        pytest.skip(f"演示脚本缺失：{DEMO_SCRIPT}")
    spec = importlib.util.spec_from_file_location("hallucination_demo", DEMO_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.skip(f"无法加载演示脚本：{DEMO_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def records() -> list:
    if not SAMPLE.exists():
        pytest.skip(f"样例日志缺失：{SAMPLE}")
    parsed, _ = parse_log_file(SAMPLE)
    return parsed


class TestDemoScriptRuns:
    def test_script_exits_zero(self, demo_module: ModuleType) -> None:
        """脚本自检全过时退出码为 0。"""
        assert demo_module.main() == 0


class TestHallucinationsAreBlocked:
    def test_fabricated_device_is_rejected(self, demo_module: ModuleType, records: list) -> None:
        """虚构的设备编号必须整条剔除。"""
        draft = demo_module.build_hallucinated_draft(records)
        cleaned, rejected = demo_module.validate_findings(draft, records)
        kept = {f.device_id for f in cleaned}
        assert "RF-DET-99" not in kept
        assert any("RF-DET-99" in message for message in rejected)

    def test_fabricated_evidence_is_dropped(self, demo_module: ModuleType, records: list) -> None:
        """伪造的证据行不能进入最终报告。"""
        draft = demo_module.build_hallucinated_draft(records)
        cleaned, _ = demo_module.validate_findings(draft, records)
        all_evidence = [line for f in cleaned for line in f.evidence]
        assert demo_module.FAKE_LASER_EVIDENCE not in all_evidence
        assert demo_module.FAKE_RADAR_EVIDENCE not in all_evidence

    def test_real_evidence_is_kept_not_wholesale_replaced(
        self, demo_module: ModuleType, records: list
    ) -> None:
        """真实证据行要逐条保留，而不是因为混了假行就整份被替换。

        这是闸门设计的关键：一刀切替换会丢掉模型引用的原始行，
        让报告失去可追溯性。
        """
        draft = demo_module.build_hallucinated_draft(records)
        cleaned, _ = demo_module.validate_findings(draft, records)
        laser = next(f for f in cleaned if f.device_id == "LASER-01")
        assert demo_module.pick_real_line(records, "LASER-01", "自检失败") in laser.evidence

    def test_wrong_device_kind_is_corrected(self, demo_module: ModuleType, records: list) -> None:
        """设备类型张冠李戴时，闸门按日志纠正回来。"""
        draft = demo_module.build_hallucinated_draft(records)
        cleaned, _ = demo_module.validate_findings(draft, records)
        rd_eo_01 = next(f for f in cleaned if f.device_id == "RD-EO-01")
        assert rd_eo_01.device_kind.value == "雷达+视觉设备"

    def test_overall_status_is_recomputed(self, demo_module: ModuleType, records: list) -> None:
        """整体状态按清洗后的问题项重算，不沿用模型给的虚高值。"""
        draft = demo_module.build_hallucinated_draft(records)
        cleaned, _ = demo_module.validate_findings(draft, records)
        recomputed = demo_module.resolve_overall_status(draft.overall_status, cleaned)
        assert recomputed is not draft.overall_status
        assert recomputed.value == "严重"


class TestEvidenceProvenance:
    def test_every_kept_evidence_exists_in_log(
        self, demo_module: ModuleType, records: list
    ) -> None:
        """留在报告里的每一条证据都必须在原始日志中逐字命中。"""
        draft = demo_module.build_hallucinated_draft(records)
        cleaned, _ = demo_module.validate_findings(draft, records)
        for finding in cleaned:
            for line in finding.evidence:
                assert demo_module.evidence_exists(line, records), line

    def test_real_evidence_uses_exact_log_spacing(self, records: list) -> None:
        """现场日志的级别字段后面是两个空格——手写证据很容易少一个。

        这条测试守住「演示脚本里的真实证据」与日志原文逐字一致，
        否则闸门会把真证据误判成假证据。
        """
        laser = [r for r in records if r.device_id == "LASER-01" and r.level == "ERROR"]
        assert laser, "样例日志里应有 LASER-01 的 ERROR 行"
        assert all("ERROR  " in r.raw for r in laser)
