"""README 的真实性校验。

README 首屏是招聘方看到的第一份东西，它里面写的每一个数字、
每一段命令输出都必须是真的——否则就是「用文档掩盖代码没跑通」。

所以这里做三件事：

1. README 里引用的每个相对链接都指向真实存在的文件；
2. README 里贴的命令输出，逐行都能在脚本真实输出里找到；
3. README 里声称的测试数量与覆盖率，和实际跑出来的结果一致。

第 2 条是最关键的：它保证「截图里的绿勾」不是编的。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
README = PROJECT_ROOT / "README.md"

# README 里的相对链接（跳过 http(s) / 锚点 / 邮件）
LINK_RE = re.compile(r"\]\((?!https?://|#|mailto:)([^)]+)\)")
# console 代码块
CONSOLE_BLOCK_RE = re.compile(r"```console\n(.*?)```", re.DOTALL)
# README 里声称的测试数量
TEST_COUNT_RE = re.compile(r"(\d+)\s*个用例")
COVERAGE_RE = re.compile(r"覆盖率\s*([\d.]+)%")


@pytest.fixture(scope="module")
def readme_text() -> str:
    if not README.exists():
        pytest.skip("README 不存在")
    return README.read_text(encoding="utf-8")


class TestReadmeLinks:
    def test_relative_links_point_to_real_files(self, readme_text: str) -> None:
        """README 里引用的每个相对路径都必须真实存在。"""
        missing: list[str] = []
        for target in LINK_RE.findall(readme_text):
            # 去掉锚点部分
            path_part = target.split("#", 1)[0]
            if not path_part:
                continue
            if not (PROJECT_ROOT / path_part).exists():
                missing.append(target)
        assert not missing, f"README 里这些链接指向不存在的文件：{missing}"

    def test_no_dead_example_paths(self, readme_text: str) -> None:
        """README 提到的 docs/examples/ 下三份报告都要在。"""
        for name in (
            "report_2026-10-28.md",
            "report_2026-10-29-b.md",
            "report_2026-10-30-c.md",
        ):
            assert f"docs/examples/{name}" in readme_text, f"README 未引用 {name}"
            assert (PROJECT_ROOT / "docs" / "examples" / name).exists()


class TestReadmeConsoleOutputIsReal:
    """README 里贴的命令输出必须逐行真实。"""

    @staticmethod
    def _run(script: str) -> str:
        result = subprocess.run(
            [sys.executable, script],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout + result.stderr

    def test_hallucination_demo_output_matches(self, readme_text: str) -> None:
        """README 里 `make demo-hallucination` 的输出必须是脚本真实输出。"""
        real = self._run("scripts/hallucination_demo.py")
        blocks = CONSOLE_BLOCK_RE.findall(readme_text)
        assert blocks, "README 里没有 console 代码块"

        demo_block = next((b for b in blocks if "demo-hallucination" in b), None)
        assert demo_block is not None, "README 里没有幻觉演示的输出块"

        checked = 0
        for line in demo_block.splitlines():
            stripped = line.strip()
            # 跳过命令提示符和分隔线
            if not stripped or stripped.startswith("$ "):
                continue
            if set(stripped) <= {"-", "="}:
                continue
            assert stripped in real, f"README 里的这行不是脚本真实输出：{stripped}"
            checked += 1
        assert checked >= 15, "校验的行数太少，说明对比没生效"

    def test_verify_examples_output_matches(self, readme_text: str) -> None:
        """README 里 `make verify-examples` 的输出必须是脚本真实输出。"""
        real = self._run("scripts/verify_examples.py")
        blocks = CONSOLE_BLOCK_RE.findall(readme_text)
        verify_block = next((b for b in blocks if "verify-examples" in b), None)
        assert verify_block is not None, "README 里没有样例校验的输出块"

        checked = 0
        for line in verify_block.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("$ "):
                continue
            if set(stripped) <= {"-", "="}:
                continue
            assert stripped in real, f"README 里的这行不是脚本真实输出：{stripped}"
            checked += 1
        assert checked >= 8, "校验的行数太少，说明对比没生效"


class TestReadmeNumbersAreReal:
    def test_test_count_matches_reality(self, readme_text: str) -> None:
        """README 声称的测试数量要跟实际收集到的一致。"""
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "--no-cov"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
        )
        output = result.stdout
        match = re.search(r"(\d+)\s+tests? collected", output)
        assert match is not None, f"无法从 pytest 输出里解析测试数量：\n{output[-500:]}"

        collected = int(match.group(1))
        claimed_match = TEST_COUNT_RE.search(readme_text)
        assert claimed_match is not None, "README 里没有写测试数量"
        claimed = int(claimed_match.group(1))
        assert claimed == collected, (
            f"README 声称 {claimed} 个用例，实际收集到 {collected} 个 —— "
            f"请更新 README 或补测试"
        )

    def test_coverage_claim_matches_pyproject_threshold(self, readme_text: str) -> None:
        """README 声称的覆盖率必须高于 pyproject 里的门槛。"""
        pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        threshold_match = re.search(r"--cov-fail-under=(\d+)", pyproject)
        assert threshold_match is not None, "pyproject 里找不到覆盖率门槛"

        claimed_match = COVERAGE_RE.search(readme_text)
        assert claimed_match is not None, "README 里没有写覆盖率"
        claimed = float(claimed_match.group(1))
        threshold = int(threshold_match.group(1))
        assert claimed >= threshold, (
            f"README 声称覆盖率 {claimed}%，低于 CI 门槛 {threshold}%"
        )
