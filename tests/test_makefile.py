"""Makefile 结构防回归测试。

背景：曾经把目标名写成 `demo:hallucination`，冒号只被 GNU Make 4.x 接受。
macOS 自带的是 GNU Make 3.81，遇到冒号目标名会直接让整份 Makefile 解析失败，
结果是 README 里的 `make install` / `make demo` 等所有命令全部报错，
而 CI 跑在 ubuntu-latest（Make 4.x）上察觉不到。

这类问题的特点是「本机能跑、别人机器上炸」，所以必须在仓库内固化成测试。
"""

from __future__ import annotations

import re
from pathlib import Path

MAKEFILE = Path(__file__).resolve().parents[1] / "Makefile"

# 匹配 Makefile 里的 target 定义行：行首非空白，且不含赋值号
TARGET_RE = re.compile(r"^([A-Za-z0-9._%-]+)\s*:(?!=)")

# 变量赋值与特殊目标，不属于「目标名」，单独排除
SPECIAL_TARGETS = {".PHONY", ".SUFFIXES", ".DEFAULT", ".PRECIOUS", ".SECONDARY", ".IGNORE"}


def _target_names(text: str) -> list[str]:
    """从 Makefile 文本里抽出所有 target 名。

    只看非 recipe 行（不以 Tab 开头），跳过注释、变量赋值和特殊目标。
    """
    names: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if raw_line.startswith("\t"):
            continue
        match = TARGET_RE.match(raw_line)
        if match is None:
            continue
        name = match.group(1)
        if name in SPECIAL_TARGETS:
            continue
        names.append(name)
    return names


def test_makefile_exists() -> None:
    assert MAKEFILE.exists(), f"找不到 Makefile：{MAKEFILE}"


def test_target_names_contain_no_colon() -> None:
    """目标名不能含冒号：GNU Make 3.81（macOS 自带）无法解析。"""
    text = MAKEFILE.read_text(encoding="utf-8")
    bad: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(".PHONY"):
            continue
        head, sep, tail = line.partition(":")
        if not sep:
            continue
        # 目标定义行：第一个冒号之后如果紧跟第二个冒号，说明名字里带了冒号
        if tail.startswith("="):
            continue  # 变量赋值
        if ":" in tail:
            bad.append(line)

    assert not bad, (
        "Makefile 里出现了带冒号的目标名，macOS 自带的 GNU Make 3.81 会解析失败：\n"
        + "\n".join(bad)
        + "\n请改成连字符命名，例如 demo-hallucination。"
    )


def test_expected_targets_exist() -> None:
    """README 与 CI 依赖的目标必须存在，避免文档和实现脱节。"""
    text = MAKEFILE.read_text(encoding="utf-8")
    names = set(_target_names(text))
    expected = {
        "help",
        "install",
        "test",
        "lint",
        "fmt",
        "typecheck",
        "demo",
        "demo-hallucination",
        "verify-examples",
        "doctor",
        "generate",
        "clean",
    }
    missing = expected - names
    assert not missing, f"Makefile 缺少目标：{sorted(missing)}"


def test_phony_list_matches_actual_targets() -> None:
    """.PHONY 里声明的目标必须都是真实存在的目标。"""
    text = MAKEFILE.read_text(encoding="utf-8")
    names = set(_target_names(text))

    phony_line = next(
        (line for line in text.splitlines() if line.startswith(".PHONY:")),
        None,
    )
    assert phony_line is not None, "Makefile 缺少 .PHONY 声明"

    declared = {item.strip() for item in phony_line.split(":", 1)[1].split() if item.strip()}
    missing = declared - names
    assert not missing, f".PHONY 声明了不存在的目标：{sorted(missing)}"


def test_makefile_is_parseable_by_local_make() -> None:
    """用本机 make 真正解析一次 Makefile（不执行 recipe）。

    只跑 `make -n <target>` 的解析阶段：Makefile 语法有问题时，
    即使目标名合法也可能在这里暴露。
    """
    import shutil
    import subprocess

    make_bin = shutil.which("make")
    if make_bin is None:  # pragma: no cover - 环境里没有 make 时跳过
        import pytest

        pytest.skip("本机没有 make")

    result = subprocess.run(
        [make_bin, "-n", "help"],
        cwd=str(MAKEFILE.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"本机 make 解析 Makefile 失败：\n{result.stdout}\n{result.stderr}\n"
        f"（make 版本：{make_bin}）"
    )
