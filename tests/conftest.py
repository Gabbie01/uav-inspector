"""共享测试夹具。"""

from __future__ import annotations

from pathlib import Path

import pytest

from uav_inspector.models import LogRecord
from uav_inspector.parser import parse_log_text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_LOG = PROJECT_ROOT / "data" / "samples" / "inspection_2026-10-28.log"


@pytest.fixture(autouse=True)
def isolate_from_real_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """保证测试永远不碰真实大模型，也不依赖本地 .env 里的 Key。

    背景：这个项目本地配了真实的 .env，而 Settings 默认会读它。
    如果不隔离，`test_generate_without_api_key_fails_cleanly` 之类的用例
    会真的发起网络请求——本地有 key 时必然失败，CI 上没 .env 时又恰好通过，
    属于典型的「本地挂、CI 绿」假绿 bug。

    做法：让 CLI 拿到的 Settings 忽略 .env 文件、并阻断 socket。
    """
    from uav_inspector import cli as cli_module
    from uav_inspector.config import Settings

    monkeypatch.delenv("LLM_API_KEY", raising=False)
    # cli.py 是 `from .config import get_settings`，所以必须 patch cli 模块里的那个名字
    monkeypatch.setattr(cli_module, "get_settings", lambda: Settings(_env_file=None))
    # 兜底：任何漏网的真实网络调用都会立刻失败，而不是挂起等超时
    monkeypatch.setattr(
        "socket.socket.connect",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("测试期间禁止真实网络访问")
        ),
    )


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
