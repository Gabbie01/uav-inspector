"""大模型客户端封装。

解决的问题：
- 多家服务都是 OpenAI 兼容协议，用同一套代码切换
  （DeepSeek / Moonshot / 百炼 / SiliconFlow / OpenAI）；
- 网络抖动、限流、5xx 需要重试与退避；
- 模型输出不稳定，必须用 Pydantic 校验，不合格就让模型自己修；
- 测试与离线演示不能依赖网络，故提供 FakeLLM。
"""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Protocol

from pydantic import ValidationError

from .config import Settings
from .models import LogRecord, ReportDraft, Severity
from .parser import estimate_severity
from .prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """大模型调用失败。"""


class LLMClient(Protocol):
    """大模型客户端协议，方便替换与测试。"""

    def complete_json(self, system: str, user: str) -> str:
        """返回模型生成的原始 JSON 字符串。"""
        ...


class OpenAICompatibleClient:
    """基于 openai SDK 的 OpenAI 兼容客户端。

    兼容 DeepSeek、Moonshot、阿里百炼、SiliconFlow、OpenAI 官方等。
    """

    def __init__(self, settings: Settings) -> None:
        if not settings.has_api_key:
            raise LLMError("未配置 LLM_API_KEY，请在 .env 中设置或运行 `uav-inspect doctor` 检查")
        from openai import OpenAI  # 延迟导入，避免无依赖时导入失败

        self._settings = settings
        self._client = OpenAI(
            api_key=settings.llm_api_key.get_secret_value(),
            base_url=settings.llm_base_url,
            timeout=settings.llm_timeout_s,
            max_retries=0,  # 重试由本模块统一处理，便于观测与退避控制
        )

    def complete_json(self, system: str, user: str) -> str:
        from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError

        retryable = (RateLimitError, APITimeoutError, APIConnectionError, APIStatusError)
        last_error: Exception | None = None

        for attempt in range(1, self._settings.llm_max_retries + 1):
            try:
                response = self._client.chat.completions.create(
                    model=self._settings.llm_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    temperature=self._settings.llm_temperature,
                    response_format={"type": "json_object"},
                )
                content = response.choices[0].message.content
                if not content or not content.strip():
                    raise LLMError("模型返回了空内容")
                return content
            except retryable as exc:  # noqa: PERF203
                last_error = exc
                if attempt >= self._settings.llm_max_retries:
                    break
                backoff = min(2.0**attempt + random.uniform(0, 0.5), 30.0)
                logger.warning(
                    "大模型调用失败（第 %d/%d 次），%.1fs 后重试：%s",
                    attempt,
                    self._settings.llm_max_retries,
                    backoff,
                    exc,
                )
                time.sleep(backoff)

        raise LLMError(
            f"大模型调用在 {self._settings.llm_max_retries} 次重试后仍失败：{last_error}"
        )

    def close(self) -> None:
        self._client.close()


def extract_json(raw: str) -> dict[str, Any]:
    """从模型输出中提取 JSON 对象，容忍 ```json 包裹和前后废话。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        data = json.loads(text[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError(f"模型输出不是 JSON 对象，而是 {type(data).__name__}")
    return data


def generate_draft(
    client: LLMClient,
    records: list[LogRecord],
    unparsed: list[str],
    site: str,
    *,
    max_repairs: int = 1,
) -> ReportDraft:
    """让模型产出结构化草稿，并在校验失败时让模型自行修复。

    这是整个流程里最关键的一环：**不让不合格的输出流到下游**。
    """
    user_prompt = build_user_prompt(records, unparsed, site)
    raw = client.complete_json(SYSTEM_PROMPT, user_prompt)

    try:
        data = extract_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        if max_repairs <= 0:
            raise LLMError(f"模型输出无法解析为 JSON：{exc}") from exc
        logger.warning("模型输出不是合法 JSON，触发一次修复：%s", exc)
        raw = client.complete_json(SYSTEM_PROMPT, build_repair_prompt(raw, f"JSON 解析失败：{exc}"))
        try:
            data = extract_json(raw)
        except (json.JSONDecodeError, ValueError) as exc2:
            raise LLMError(f"模型修复后仍无法解析为 JSON：{exc2}") from exc2

    try:
        return ReportDraft.model_validate(data)
    except ValidationError as exc:
        if max_repairs <= 0:
            raise LLMError(f"模型输出未通过 schema 校验：{exc}") from exc
        logger.warning("模型输出未通过 schema 校验，触发一次修复：%s", exc.errors()[:3])
        raw = client.complete_json(
            SYSTEM_PROMPT, build_repair_prompt(raw, f"schema 校验失败：{exc.errors()[:5]}")
        )
        try:
            data = extract_json(raw)
        except (json.JSONDecodeError, ValueError) as exc2:
            raise LLMError(f"模型修复后仍无法解析为 JSON：{exc2}") from exc2
        try:
            return ReportDraft.model_validate(data)
        except ValidationError as exc2:
            raise LLMError(f"模型修复后仍未通过 schema 校验：{exc2}") from exc2


class FakeLLM:
    """离线假模型：不联网，按确定性规则产出草稿。

    用途：
    - 单元测试（保证测试永不依赖外部服务）；
    - `uav-inspect demo` 离线演示，让你先看到完整流程与产出格式。
    """

    def __init__(self, *, delay: float = 0.0) -> None:
        self._delay = delay
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if self._delay:
            time.sleep(self._delay)
        # 从提示词里回捞结构化记录，复用真实解析逻辑
        records = _extract_records_from_prompt(user)
        return json.dumps(_synthesize_draft(records), ensure_ascii=False)


def _extract_records_from_prompt(user_prompt: str) -> list[LogRecord]:
    """从构造好的提示词中还原 LogRecord（仅测试/离线演示用）。"""
    start = user_prompt.find('"records": [')
    if start == -1:
        return []
    start = user_prompt.find("[", start)
    end = user_prompt.find("]\n", start)
    if end == -1:
        return []
    try:
        payload = json.loads(user_prompt[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[LogRecord] = []
    for item in payload:
        out.append(
            LogRecord(
                timestamp=item["timestamp"],
                device_id=item["device_id"],
                device_kind=item["device_kind"],
                level=item["level"],
                message=item["message"],
                # 优先使用提示词里透传的原始行，保证与真实日志逐字一致
                raw=item.get("raw")
                or f"{item['timestamp']} [{item['device_id']}] {item['level']} {item['message']}",
            )
        )
    return out


def _synthesize_draft(records: list[LogRecord]) -> dict[str, Any]:
    """离线模式下的确定性草稿生成。"""
    by_device: dict[str, list[LogRecord]] = {}
    for record in records:
        by_device.setdefault(record.device_id, []).append(record)

    findings: list[dict[str, Any]] = []
    for device_id, device_records in by_device.items():
        scored = [(estimate_severity(r), r) for r in device_records]
        severity = max(scored, key=lambda item: item[0].rank)[0]
        if severity is Severity.NORMAL:
            continue
        abnormal = [r for s, r in scored if s is not Severity.NORMAL]
        first = abnormal[0]
        findings.append(
            {
                "device_id": device_id,
                "device_kind": first.device_kind.value,
                "severity": severity.value,
                "title": f"{first.device_kind.value}{device_id} 存在{severity.value}级异常",
                "detail": "；".join(r.message for r in abnormal[:5]),
                "evidence": [r.raw for r in abnormal[:5]],
                "impact": "可能影响该区域的低空目标发现与处置连续性。",
                "recommendation": "现场复测该设备工作状态并检查供电、天线与通信链路，"
                "如仍异常则记录现象并联系厂家技术支持。",
            }
        )

    findings.sort(key=lambda f: (-Severity.coerce(f["severity"]).rank, f["device_id"]))
    highest = Severity.NORMAL
    for finding in findings:
        highest = max(highest, Severity.coerce(finding["severity"]), key=lambda s: s.rank)

    return {
        "overall_status": highest.value,
        "executive_summary": (
            f"本次巡检共解析 {len(records)} 条日志，涉及 {len(by_device)} 台设备，"
            f"识别出 {len(findings)} 项需要处理的问题，最高风险等级为{highest.value}。"
        ),
        "findings": findings,
        "immediate_actions": ["核对异常设备现场是否仍处于告警状态并做临时处置"] if findings else [],
        "follow_up_actions": ["整理异常设备清单并提交厂家技术支持工单"] if findings else [],
    }
