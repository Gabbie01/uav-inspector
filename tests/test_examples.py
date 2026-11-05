"""真实报告样例（docs/examples/）的回归测试。

背景：`docs/examples/` 里放的是用真实大模型跑出来的报告样例，
是招聘方打开仓库第一眼会看的「硬证据」。这类文件有个隐患：
改了 prompt、闸门或解析逻辑之后，样例报告可能悄悄过期
（统计口径变了、设备类型改了），但没人会发现。

所以这里把 scripts/verify_examples.py 的判据搬进 pytest：
拿原始日志当唯一真相，逐条回查报告里的证据行、设备编号、
分级统计与头部统计。

另外两条用例确保「校验器本身不是空转的」——
故意造一份有问题的报告，校验器必须能抓到。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from uav_inspector.parser import parse_log_file

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify_examples.py"
EXAMPLES_DIR = PROJECT_ROOT / "docs" / "examples"

LOG_SUFFIX_TO_REPORT = {
    "2026-10-28": "report_2026-10-28.md",
    "2026-10-29-b": "report_2026-10-29-b.md",
    "2026-10-30-c": "report_2026-10-30-c.md",
}


@pytest.fixture(scope="module")
def verify_module() -> ModuleType:
    """按文件路径加载校验脚本（scripts/ 不是包，不能直接 import）。"""
    if not VERIFY_SCRIPT.exists():
        pytest.skip(f"校验脚本缺失：{VERIFY_SCRIPT}")
    spec = importlib.util.spec_from_file_location("verify_examples", VERIFY_SCRIPT)
    if spec is None or spec.loader is None:
        pytest.skip(f"无法加载校验脚本：{VERIFY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestExamplesExist:
    @pytest.mark.parametrize("report_name", sorted(LOG_SUFFIX_TO_REPORT.values()))
    def test_report_file_exists(self, report_name: str) -> None:
        """三份现场报告必须都在仓库里。"""
        path = EXAMPLES_DIR / report_name
        assert path.exists(), f"缺少报告样例：{path.relative_to(PROJECT_ROOT)}"

    def test_three_distinct_sites(self) -> None:
        """三份报告必须来自三个不同现场，不能是同一份复制三遍。"""
        sites = set()
        for report_name in LOG_SUFFIX_TO_REPORT.values():
            path = EXAMPLES_DIR / report_name
            if not path.exists():
                pytest.skip(f"缺少报告样例：{path}")
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("- **现场**"):
                    sites.add(line.split("：", 1)[1].strip())
                    break
        assert len(sites) == len(LOG_SUFFIX_TO_REPORT), f"现场名重复：{sites}"


class TestExamplesAreFactuallyConsistent:
    @pytest.mark.parametrize("log_suffix", sorted(LOG_SUFFIX_TO_REPORT))
    def test_report_matches_source_log(
        self, verify_module: ModuleType, log_suffix: str
    ) -> None:
        """每份报告的证据行、设备编号、统计都必须与原始日志一致。"""
        problems = verify_module.verify_one(log_suffix, LOG_SUFFIX_TO_REPORT[log_suffix])
        assert not problems, "报告与原始日志不一致：\n" + "\n".join(problems)

    def test_script_exits_zero(self, verify_module: ModuleType) -> None:
        """校验脚本整体跑通，退出码为 0。"""
        assert verify_module.main() == 0


class TestVerifierActuallyDetectsProblems:
    """校验器必须真的能抓到问题，否则上面的 PASS 没有意义。"""

    def test_detects_fabricated_evidence(
        self, verify_module: ModuleType, tmp_path: Path
    ) -> None:
        """把报告里某条证据改掉，校验器必须报出来。"""
        report_name = "report_2026-10-30-c.md"
        original = (EXAMPLES_DIR / report_name).read_text(encoding="utf-8")
        tampered = original.replace("E-104", "E-999")
        assert tampered != original, "篡改没有生效，样例内容可能变了"

        fake_dir = tmp_path / "examples"
        fake_dir.mkdir()
        (fake_dir / report_name).write_text(tampered, encoding="utf-8")

        original_dir = verify_module.EXAMPLES_DIR
        verify_module.EXAMPLES_DIR = fake_dir
        try:
            problems = verify_module.verify_one("2026-10-30-c", report_name)
        finally:
            verify_module.EXAMPLES_DIR = original_dir

        assert problems, "篡改证据行后校验器竟然没报错"
        assert any("逐字匹配" in p for p in problems)

    def test_detects_unknown_device(self, verify_module: ModuleType, tmp_path: Path) -> None:
        """把设备编号改成日志里不存在的，校验器必须报出来。"""
        report_name = "report_2026-10-30-c.md"
        original = (EXAMPLES_DIR / report_name).read_text(encoding="utf-8")
        tampered = original.replace("LASER-01", "LASER-99")
        assert tampered != original

        fake_dir = tmp_path / "examples"
        fake_dir.mkdir()
        (fake_dir / report_name).write_text(tampered, encoding="utf-8")

        original_dir = verify_module.EXAMPLES_DIR
        verify_module.EXAMPLES_DIR = fake_dir
        try:
            problems = verify_module.verify_one("2026-10-30-c", report_name)
        finally:
            verify_module.EXAMPLES_DIR = original_dir

        assert problems, "篡改设备编号后校验器竟然没报错"
        assert any("不存在的设备" in p for p in problems)


class TestEvidenceLinesAreVerbatim:
    @pytest.mark.parametrize("log_suffix", sorted(LOG_SUFFIX_TO_REPORT))
    def test_every_evidence_line_verbatim(self, log_suffix: str) -> None:
        """报告里引用的每条证据行，都必须能在原始日志中逐字命中。

        这条不依赖校验脚本，是最底层的兜底断言。
        """
        log_path = PROJECT_ROOT / "data" / "samples" / f"inspection_{log_suffix}.log"
        report_path = EXAMPLES_DIR / LOG_SUFFIX_TO_REPORT[log_suffix]
        if not log_path.exists() or not report_path.exists():
            pytest.skip("样例日志或报告缺失")

        records, _ = parse_log_file(log_path)
        raw_lines = {r.raw for r in records}

        report_text = report_path.read_text(encoding="utf-8")
        evidence = []
        in_block = False
        for raw in report_text.splitlines():
            stripped = raw.strip()
            if stripped.startswith("```"):
                in_block = not in_block
                continue
            if in_block and stripped[:4].isdigit() and "[" in stripped:
                evidence.append(stripped)

        assert evidence, "报告里没找到证据行"
        for line in evidence:
            assert line in raw_lines, f"证据行不是日志原文：{line}"
