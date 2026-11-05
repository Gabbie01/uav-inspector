"""共享测试夹具。"""

from __future__ import annotations

from pathlib import Path

import pytest

from uav_inspector.models import LogRecord
from uav_inspector.parser import parse_log_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_LOG = PROJECT_ROOT / "data" / "samples" / "inspection_2026-10-28.log"


@pytest.fixture(scope="session")
def sample_log_path() -> Path:
    if not SAMPLE_LOG.exists():
        pytest.skip(f"样例日志缺失：{SAMPLE_LOG}")
    return SAMPLE_LOG


@pytest.fixture(scope="session")
def sample_log_text(sample_log_path: Path) -> str:
    return sample_log_path.read_text(encoding="utf-8")


@pytest.fixture(scope="session")
def parsed(sample_log_text: str) -> tuple[list[LogRecord], list[str]]:
    return parse_log_text(sample_log_text)


@pytest.fixture(scope="session")
def records(parsed: tuple[list[LogRecord], list[str]]) -> list[LogRecord]:
    return parsed[0]


@pytest.fixture(scope="session")
def unparsed(parsed: tuple[list[LogRecord], list[str]]) -> list[str]:
    return parsed[1]
