"""CLI 端到端测试：demo / doctor / generate 三个子命令。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uav_inspector.cli import main


class TestDemo:
    def test_demo_runs_without_api_key(
        self, sample_log_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["demo", "--log", str(sample_log_path)])
        assert code == 0
        out = capsys.readouterr().out
        assert "解析 51 条记录" in out
        assert "反无人机设备巡检报告" in out

    def test_demo_writes_output_file(
        self, sample_log_path: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = tmp_path / "nested" / "report.md"
        code = main(["demo", "--log", str(sample_log_path), "--output", str(target)])
        assert code == 0
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert "# 反无人机设备巡检报告" in content
        assert "报告已写入" in capsys.readouterr().out

    def test_demo_text_format(self, sample_log_path: Path, tmp_path: Path) -> None:
        target = tmp_path / "report.txt"
        code = main(
            ["demo", "--log", str(sample_log_path), "--output", str(target), "--format", "text"]
        )
        assert code == 0
        assert "【执行摘要】" in target.read_text(encoding="utf-8")

    def test_demo_rejects_missing_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["demo", "--log", str(tmp_path / "nope.log")])
        assert code == 1
        assert "样例日志不存在" in capsys.readouterr().err


class TestDoctor:
    def test_doctor_without_api_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        code = main(["doctor"])
        assert code == 0
        out = capsys.readouterr().out
        assert "uav-inspector 环境自检" in out
        assert "Python" in out
        assert "base_url" in out

    def test_doctor_reports_sample_stats(self, capsys: pytest.CaptureFixture[str]) -> None:
        main(["doctor"])
        out = capsys.readouterr().out
        assert "51 条可解析" in out


class TestGenerate:
    def test_generate_without_api_key_fails_cleanly(
        self, sample_log_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        code = main(["generate", str(sample_log_path)])
        assert code == 2
        err = capsys.readouterr().err
        assert "未配置 LLM_API_KEY" in err

    def test_generate_uses_stub_model(
        self,
        sample_log_path: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """用假客户端替换真实模型，验证 generate 的完整链路。"""

        from uav_inspector import cli as cli_module

        class StubClient:
            def __init__(self, settings: object) -> None:
                self.settings = settings

            def complete_json(self, system: str, user: str) -> str:
                return json.dumps(
                    {
                        "overall_status": "严重",
                        "executive_summary": "离线摘要。",
                        "findings": [
                            {
                                "device_id": "RF-JAM-01",
                                "device_kind": "无线电电压制设备",
                                "severity": "严重",
                                "title": "压制设备离线",
                                "detail": "压制设备离线",
                                "evidence": [],
                            }
                        ],
                        "immediate_actions": [],
                        "follow_up_actions": [],
                    },
                    ensure_ascii=False,
                )

            def close(self) -> None:
                return None

        monkeypatch.setattr(cli_module, "OpenAICompatibleClient", StubClient)
        monkeypatch.setattr(cli_module, "get_settings", lambda: _settings_with_key())

        target = tmp_path / "out.md"
        code = main(["generate", str(sample_log_path), "--output", str(target)])
        assert code == 0
        content = target.read_text(encoding="utf-8")
        assert "压制设备离线" in content


def _settings_with_key() -> object:
    from uav_inspector.config import Settings

    return Settings(llm_api_key="test-key")  # type: ignore[arg-type]
