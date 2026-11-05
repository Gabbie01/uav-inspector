"""LLM 客户端层测试：JSON 提取、结构化输出、校验失败后的修复重试。

全部使用假客户端，测试永不联网。
"""

from __future__ import annotations

import json

import pytest

from uav_inspector.llm import (
    FakeLLM,
    LLMError,
    extract_json,
    generate_draft,
)
from uav_inspector.models import DeviceKind, LogRecord, Severity


class ScriptedLLM:
    """按预设脚本依次返回内容的假客户端。"""

    def __init__(self, *responses: str) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if not self._responses:
            raise AssertionError("ScriptedLLM 的响应已用尽，但代码又发起了一次调用")
        return self._responses.pop(0)


def _record(
    device_id: str = "RF-DET-01",
    message: str = "设备离线",
    level: str = "ERROR",
) -> LogRecord:
    return LogRecord(
        timestamp="2026-10-28 08:12:03",
        device_id=device_id,
        device_kind=DeviceKind.RF_DETECT,
        level=level,
        message=message,
        raw=f"2026-10-28 08:12:03 [{device_id}] {level} {message}",
    )


class TestExtractJson:
    def test_plain_json(self) -> None:
        assert extract_json('{"a": 1}') == {"a": 1}

    def test_markdown_fenced(self) -> None:
        assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

    def test_bare_fence(self) -> None:
        assert extract_json('```\n{"a": 1}\n```') == {"a": 1}

    def test_json_with_surrounding_prose(self) -> None:
        raw = '好的，这是结果：{"a": 1} 希望有帮助。'
        assert extract_json(raw) == {"a": 1}

    def test_non_object_rejected(self) -> None:
        with pytest.raises(ValueError):
            extract_json("[1, 2, 3]")

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            extract_json("完全不是 JSON")


class TestGenerateDraft:
    def test_valid_output_accepted(self) -> None:
        payload = json.dumps(
            {
                "overall_status": "严重",
                "executive_summary": "有一台设备离线。",
                "findings": [
                    {
                        "device_id": "RF-DET-01",
                        "device_kind": "射频信号侦测设备",
                        "severity": "严重",
                        "title": "射频侦测设备离线",
                        "detail": "设备离线",
                        "evidence": [],
                    }
                ],
                "immediate_actions": ["现场确认"],
                "follow_up_actions": [],
            },
            ensure_ascii=False,
        )
        client = ScriptedLLM(payload)
        draft = generate_draft(client, [_record()], [], "测试现场")
        assert draft.overall_status is Severity.HIGH
        assert len(draft.findings) == 1
        assert len(client.calls) == 1  # 一次通过，没有触发修复

    def test_invalid_json_triggers_repair(self) -> None:
        good = json.dumps(
            {
                "overall_status": "正常",
                "executive_summary": "已修复。",
                "findings": [],
                "immediate_actions": [],
                "follow_up_actions": [],
            },
            ensure_ascii=False,
        )
        client = ScriptedLLM("这不是 JSON", good)
        draft = generate_draft(client, [_record()], [], "测试现场")
        assert draft.executive_summary == "已修复。"
        assert len(client.calls) == 2

    def test_schema_violation_triggers_repair(self) -> None:
        # 缺少必填字段 executive_summary
        bad = json.dumps({"overall_status": "正常", "findings": []}, ensure_ascii=False)
        good = json.dumps(
            {
                "overall_status": "正常",
                "executive_summary": "正常。",
                "findings": [],
                "immediate_actions": [],
                "follow_up_actions": [],
            },
            ensure_ascii=False,
        )
        client = ScriptedLLM(bad, good)
        draft = generate_draft(client, [_record()], [], "测试现场")
        assert draft.executive_summary == "正常。"
        assert len(client.calls) == 2

    def test_repair_also_fails_raises_llm_error(self) -> None:
        client = ScriptedLLM("garbage", "still garbage")
        with pytest.raises(LLMError):
            generate_draft(client, [_record()], [], "测试现场")

    def test_no_repair_allowed_raises(self) -> None:
        client = ScriptedLLM("garbage")
        with pytest.raises(LLMError):
            generate_draft(client, [_record()], [], "测试现场", max_repairs=0)

    def test_repair_prompt_contains_error_and_previous_output(self) -> None:
        good = json.dumps(
            {
                "overall_status": "正常",
                "executive_summary": "ok",
                "findings": [],
                "immediate_actions": [],
                "follow_up_actions": [],
            },
            ensure_ascii=False,
        )
        client = ScriptedLLM("garbage", good)
        generate_draft(client, [_record()], [], "测试现场")
        repair_user_prompt = client.calls[1][1]
        assert "garbage" in repair_user_prompt
        assert "校验错误" in repair_user_prompt


class TestFakeLLM:
    def test_produces_valid_draft(self, records: list[LogRecord]) -> None:
        client = FakeLLM()
        draft = generate_draft(client, records, [], "测试现场")
        assert draft.executive_summary
        assert draft.findings

    def test_evidence_is_verbatim_log_line(self, records: list[LogRecord]) -> None:
        client = FakeLLM()
        draft = generate_draft(client, records, [], "测试现场")
        raw_lines = {r.raw for r in records}
        for finding in draft.findings:
            for evidence in finding.evidence:
                assert evidence in raw_lines

    def test_no_normal_device_becomes_finding(self) -> None:
        client = FakeLLM()
        draft = generate_draft(
            client, [_record("LASER-01", "设备运行正常", level="INFO")], [], "测试"
        )
        assert draft.findings == []

    def test_records_prompt_includes_raw_line(self, records: list[LogRecord]) -> None:
        client = FakeLLM()
        client.complete_json("system", "x")
        client = FakeLLM()
        generate_draft(client, records[:1], [], "测试")
        assert client.calls
        _, user_prompt = client.calls[0]
        assert records[0].raw in user_prompt
