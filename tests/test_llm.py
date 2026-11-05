"""LLM 客户端层测试：JSON 提取、结构化输出、校验失败后的修复重试。

全部使用假客户端，测试永不联网。
"""

from __future__ import annotations

import json

import pytest

from uav_inspector.llm import (
    FakeLLM,
    LLMError,
    OpenAICompatibleClient,
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


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """模拟 openai SDK 的 client.chat.completions.create。"""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.kwargs: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> _FakeResponse:
        self.kwargs.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, str)
        return _FakeResponse(outcome)


class _FakeOpenAI:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = type("_Chat", (), {"completions": completions})()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _make_client(
    monkeypatch: pytest.MonkeyPatch, outcomes: list[object], **settings_kwargs: object
) -> tuple[OpenAICompatibleClient, _FakeCompletions]:
    """构造一个注入了假 OpenAI 客户端的 OpenAICompatibleClient。"""
    import openai

    from uav_inspector.config import Settings

    completions = _FakeCompletions(*outcomes)
    fake = _FakeOpenAI(completions)
    monkeypatch.setattr(openai, "OpenAI", lambda **kwargs: fake)

    base: dict[str, object] = {
        "llm_api_key": "test-key",
        "llm_base_url": "https://example.invalid/v1",
        "llm_model": "test-model",
        "llm_timeout_s": 1.0,
        "llm_max_retries": 3,
        "_env_file": None,
    }
    base.update(settings_kwargs)
    settings = Settings(**base)  # type: ignore[arg-type]
    return OpenAICompatibleClient(settings), completions


def _sdk_error(kind: str) -> Exception:
    """构造一个真实的 openai SDK 异常实例（不联网）。"""
    import httpx2
    import openai

    request = httpx2.Request("POST", "https://example.invalid/v1/chat/completions")
    if kind == "timeout":
        return openai.APITimeoutError(request=request)
    if kind == "connection":
        return openai.APIConnectionError(request=request)
    if kind == "rate_limit":
        response = httpx2.Response(429, request=request)
        return openai.RateLimitError("触发限流", response=response, body=None)
    if kind == "server":
        response = httpx2.Response(500, request=request)
        return openai.APIStatusError("服务端错误", response=response, body=None)
    raise ValueError(f"未知的异常类型：{kind}")


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """拦截退避 sleep，记录调用间隔但真的不睡。"""
    from uav_inspector import llm as llm_module

    slept: list[float] = []
    monkeypatch.setattr(llm_module.time, "sleep", lambda seconds: slept.append(seconds))
    return slept


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


class TestOpenAICompatibleClient:
    """真实客户端的重试/退避/错误包装行为，全部通过 mock 离线验证。"""

    def test_success_returns_content(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client, completions = _make_client(monkeypatch, ['{"ok": true}'])
        assert client.complete_json("sys", "usr") == '{"ok": true}'
        assert len(completions.kwargs) == 1

    def test_request_parameters(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client, completions = _make_client(
            monkeypatch, ['{"ok": true}'], llm_model="my-model", llm_temperature=0.7
        )
        client.complete_json("sys", "usr")
        kwargs = completions.kwargs[0]
        assert kwargs["model"] == "my-model"
        assert kwargs["temperature"] == 0.7
        assert kwargs["response_format"] == {"type": "json_object"}
        messages = kwargs["messages"]
        assert isinstance(messages, list)
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "sys"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "usr"

    @pytest.mark.parametrize(
        "kind", ["timeout", "connection", "rate_limit", "server"]
    )
    def test_retryable_error_then_success(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float], kind: str
    ) -> None:
        client, completions = _make_client(
            monkeypatch, [_sdk_error(kind), '{"ok": true}']
        )
        assert client.complete_json("sys", "usr") == '{"ok": true}'
        assert len(completions.kwargs) == 2
        assert len(no_sleep) == 1  # 退避一次

    def test_exhausted_retries_raises_llm_error(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
    ) -> None:
        client, completions = _make_client(
            monkeypatch,
            [_sdk_error("timeout") for _ in range(3)],
            llm_max_retries=3,
        )
        with pytest.raises(LLMError) as excinfo:
            client.complete_json("sys", "usr")
        assert "3 次重试" in str(excinfo.value)
        assert len(completions.kwargs) == 3
        assert len(no_sleep) == 2  # 最后一次失败后不再退避

    def test_backoff_grows_and_is_capped(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
    ) -> None:
        client, _ = _make_client(
            monkeypatch,
            [_sdk_error("timeout") for _ in range(6)],
            llm_max_retries=6,
        )
        with pytest.raises(LLMError):
            client.complete_json("sys", "usr")
        assert len(no_sleep) == 5
        assert all(s > 0 for s in no_sleep)
        assert all(s <= 30.0 for s in no_sleep)
        assert no_sleep[0] < no_sleep[-1]  # 指数退避递增

    def test_non_retryable_error_propagates_immediately(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
    ) -> None:
        boom = ValueError("参数不合法")
        client, completions = _make_client(monkeypatch, [boom])
        with pytest.raises(ValueError):
            client.complete_json("sys", "usr")
        assert len(completions.kwargs) == 1
        assert no_sleep == []

    def test_empty_content_raises_llm_error(
        self, monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
    ) -> None:
        client, completions = _make_client(monkeypatch, ["   "])
        with pytest.raises(LLMError) as excinfo:
            client.complete_json("sys", "usr")
        assert "空内容" in str(excinfo.value)
        assert len(completions.kwargs) == 1

    def test_missing_api_key_raises_llm_error(self) -> None:
        from uav_inspector.config import Settings

        settings = Settings(llm_api_key="", _env_file=None)  # type: ignore[arg-type]
        with pytest.raises(LLMError) as excinfo:
            OpenAICompatibleClient(settings)
        assert "LLM_API_KEY" in str(excinfo.value)

    def test_close_delegates_to_sdk(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import openai

        client, _ = _make_client(monkeypatch, ['{"ok": true}'])
        fake = client._client  # noqa: SLF001 - 测试内部状态
        assert isinstance(fake, _FakeOpenAI)
        client.close()
        assert fake.closed is True
        assert openai is not None
