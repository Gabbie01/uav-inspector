"""提示词模板。

设计原则：
1. 角色设定贴近用户真实岗位（低空安全/反无人机现场交付工程师），不是通用助理；
2. 输入数据以结构化方式给出，降低模型理解成本；
3. 显式给出输出 schema，让模型即使在不支持 json_schema 的服务上也能稳定产出可校验 JSON；
4. 明确"不得编造"约束，并在后处理阶段做二次校验。
"""

from __future__ import annotations

import json
from typing import Any

from .models import LogRecord, ReportDraft, Severity
from .parser import estimate_severity

SYSTEM_PROMPT = """你是一名资深反无人机系统的现场运维与技术支持工程师，负责把现场巡检日志\
转化为可交付的结构化运维报告。

你的判断必须基于给定的巡检记录，不要编造未出现的事实、参数或数值。

工作准则：
- 风险等级：正常 / 轻微 / 中等 / 严重 / 紧急。
- 同一台设备的多条相关记录应合并为一个问题项，并在 evidence 中保留原始日志行。
- 只把真正需要人处理的问题列入 findings；设备正常运行无需列入。
- recommendation 必须是现场可执行的动作（检查、复位、标定、换件、联系厂家等），\
不要写"建议关注""加强监控"这类空话。
- immediate_actions 是今天/当班必须做的事；follow_up_actions 是本周内闭环的事。
- 全部输出使用简体中文。"""

DRAFT_SCHEMA_HINT = """请只输出一个 JSON 对象，不要包含 markdown 代码块标记，
不要输出任何解释性文字。
JSON 结构如下：
{
  "overall_status": "正常|轻微|中等|严重|紧急",
  "executive_summary": "一段话概述本次巡检整体情况与核心结论",
  "findings": [
    {
      "device_id": "设备编号",
      "device_kind": "无线电电压制设备|射频信号侦测设备|雷达+视觉设备|激光设备|未知设备",
      "severity": "正常|轻微|中等|严重|紧急",
      "title": "不超过30字的问题标题",
      "detail": "问题现象与初步判断",
      "evidence": ["支撑该判断的原始日志行"],
      "impact": "对现场防护能力的影响",
      "recommendation": "具体的现场处置建议"
    }
  ],
  "immediate_actions": ["当班必须执行的处置动作"],
  "follow_up_actions": ["本周内需要闭环的动作"]
}"""

SEVERITY_PRIOR = {
    Severity.NORMAL: "正常",
    Severity.LOW: "轻微",
    Severity.MEDIUM: "中等",
    Severity.HIGH: "严重",
    Severity.CRITICAL: "紧急",
}


def _record_to_dict(record: LogRecord) -> dict[str, Any]:
    # raw 是原始日志行，模型必须原样引用它作为 evidence，
    # 这样下游的事实校验才能用原文比对，识别出编造的证据。
    return {
        "timestamp": record.timestamp,
        "device_id": record.device_id,
        "device_kind": record.device_kind.value,
        "level": record.level,
        "severity_prior": SEVERITY_PRIOR[estimate_severity(record)],
        "message": record.message,
        "raw": record.raw,
    }


def build_user_prompt(records: list[LogRecord], unparsed: list[str], site: str) -> str:
    """构造用户提示词。"""
    payload = {
        "site": site,
        "log_count": len(records),
        "records": [_record_to_dict(r) for r in records],
    }
    parts = [
        f"现场位置：{site}",
        "",
        "以下是巡检日志记录（severity_prior 是依据日志级别与关键词给出的先验等级，"
        "供你参考，可结合多条记录综合调整）：",
        "<inspection_logs>",
        json.dumps(payload, ensure_ascii=False, indent=2),
        "</inspection_logs>",
    ]
    if unparsed:
        parts.extend(
            [
                "",
                f"另有 {len(unparsed)} 行无法解析的原始内容（可能是多行日志或格式异常），"
                "如其中含有重要信息，请在 detail 中说明；否则可忽略：",
                "<unparsed>",
                "\n".join(unparsed[:50]),
                "</unparsed>",
            ]
        )
    parts.extend(["", DRAFT_SCHEMA_HINT])
    return "\n".join(parts)


def build_repair_prompt(raw_output: str, error: str) -> str:
    """校验失败后的修复提示词：把错误和原始输出回灌给模型让它重写。"""
    return (
        "你上一次的输出不符合要求，未能通过 schema 校验。\n"
        f"校验错误：{error}\n\n"
        "你上一次的输出：\n"
        f"{raw_output[:4000]}\n\n"
        "请重新输出，严格符合以下 JSON 结构，只输出 JSON 本身：\n"
        f"{DRAFT_SCHEMA_HINT}"
    )


__all__ = [
    "SYSTEM_PROMPT",
    "DRAFT_SCHEMA_HINT",
    "build_repair_prompt",
    "build_user_prompt",
    "ReportDraft",
]
