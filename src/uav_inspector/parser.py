"""巡检日志解析器。

这一层是纯确定性逻辑：正则 + 关键词表，不依赖任何模型。
这样做的理由是——现场日志格式是稳定的，用代码解析又快又准，
把算力和不确定性留给真正需要判断的地方。
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import DeviceKind, LogRecord, Severity

# 形如：2026-10-28 08:12:33 [RF-DET-01] WARN 探测到持续 2.4G 信号
LOG_PATTERN = re.compile(
    r"^\s*"
    r"(?P<timestamp>\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})"
    r"\s*"
    r"\[(?P<device>[A-Za-z0-9\-_]+)\]"
    r"\s*"
    r"(?P<level>WARNING|WARN|INFO|ERROR|CRITICAL|DEBUG)"
    r"\s*"
    r"(?P<message>.+?)\s*$"
)

# 关键词 -> 初始风险等级。用于给模型一个先验，避免模型从零判断。
KEYWORD_SEVERITY: tuple[tuple[str, Severity], ...] = (
    ("紧急", Severity.CRITICAL),
    ("离线", Severity.CRITICAL),
    ("中断", Severity.CRITICAL),
    ("起火", Severity.CRITICAL),
    ("失控", Severity.CRITICAL),
    ("失败", Severity.HIGH),
    ("故障", Severity.HIGH),
    ("异常", Severity.HIGH),
    ("错误", Severity.HIGH),
    ("告警", Severity.MEDIUM),
    ("超时", Severity.MEDIUM),
    ("复位", Severity.MEDIUM),
    ("漂移", Severity.MEDIUM),
    ("偏离", Severity.MEDIUM),
    ("下降", Severity.MEDIUM),
    ("衰减", Severity.LOW),
    ("波动", Severity.LOW),
    ("偏高", Severity.LOW),
    ("偏低", Severity.LOW),
)

# 日志级别 -> 基础等级
LEVEL_SEVERITY: dict[str, Severity] = {
    "DEBUG": Severity.NORMAL,
    "INFO": Severity.NORMAL,
    "WARN": Severity.MEDIUM,
    "WARNING": Severity.MEDIUM,
    "ERROR": Severity.HIGH,
    "CRITICAL": Severity.CRITICAL,
}


def device_kind_of(device_id: str) -> DeviceKind:
    """由设备编号推断设备类型。

    编号形如 RF-DET-01 / RD-EO-02 / LASER-01 / LASER。
    从最长前缀往回匹配，避免 LASER-01 这类两段编号被拼成 "LASER-01" 而查不到映射。
    """
    parts = device_id.upper().split("-")
    for size in range(min(len(parts), 2), 0, -1):
        prefix = "-".join(parts[:size])
        kind = DeviceKind.from_prefix(prefix)
        if kind is not DeviceKind.UNKNOWN:
            return kind
    return DeviceKind.UNKNOWN


def parse_log_text(text: str) -> tuple[list[LogRecord], list[str]]:
    """解析日志文本。

    返回 (解析成功的记录列表, 无法解析的原始行列表)。
    无法解析的行不丢弃，交给上层在报告里如实标注。
    """
    records: list[LogRecord] = []
    unparsed: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = LOG_PATTERN.match(stripped)
        if match is None:
            unparsed.append(stripped)
            continue
        device_id = match.group("device")
        records.append(
            LogRecord(
                timestamp=match.group("timestamp"),
                device_id=device_id,
                device_kind=device_kind_of(device_id),
                level=match.group("level").upper(),
                message=match.group("message").strip(),
                raw=stripped,
            )
        )

    return records, unparsed


def parse_log_file(path: str | Path) -> tuple[list[LogRecord], list[str]]:
    """从文件读取并解析日志。"""
    return parse_log_text(Path(path).read_text(encoding="utf-8"))


def estimate_severity(record: LogRecord) -> Severity:
    """基于级别与关键词给出一条记录的先验风险等级。"""
    level_severity = LEVEL_SEVERITY.get(record.level, Severity.NORMAL)
    keyword_severity = Severity.NORMAL
    for keyword, severity in KEYWORD_SEVERITY:
        if keyword in record.message:
            keyword_severity = max(keyword_severity, severity, key=lambda s: s.rank)
            break
    return max(level_severity, keyword_severity, key=lambda s: s.rank)
