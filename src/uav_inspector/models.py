"""数据模型：日志解析结果、大模型结构化输出、最终报告。

这一层是整个项目的契约中心。Pydantic 模型同时承担三个职责：
1. 解析阶段的强类型数据结构；
2. 大模型 JSON 输出的校验 schema（模型输出必须能通过校验，否则触发修复重试）；
3. 最终报告的序列化格式。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(StrEnum):
    """风险等级。值即中文展示名，便于直接渲染。"""

    NORMAL = "正常"
    LOW = "轻微"
    MEDIUM = "中等"
    HIGH = "严重"
    CRITICAL = "紧急"

    @property
    def rank(self) -> int:
        """排序权重，数字越大越严重。"""
        return _SEVERITY_RANK[self]

    @classmethod
    def coerce(cls, value: Any) -> Severity:
        """容错解析：接受大小写变体、中英文同义词。"""
        if isinstance(value, cls):
            return value
        text = str(value).strip()
        for member in cls:
            if text == member.value or text.upper() == member.name:
                return member
        alias = _SEVERITY_ALIASES.get(text.lower())
        if alias is not None:
            return alias
        raise ValueError(f"无法识别的风险等级: {value!r}")


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.NORMAL: 0,
    Severity.LOW: 1,
    Severity.MEDIUM: 2,
    Severity.HIGH: 3,
    Severity.CRITICAL: 4,
}

_SEVERITY_ALIASES: dict[str, Severity] = {
    "normal": Severity.NORMAL,
    "ok": Severity.NORMAL,
    "low": Severity.LOW,
    "minor": Severity.LOW,
    "轻微": Severity.LOW,
    "medium": Severity.MEDIUM,
    "moderate": Severity.MEDIUM,
    "中等": Severity.MEDIUM,
    "high": Severity.HIGH,
    "major": Severity.HIGH,
    "严重": Severity.HIGH,
    "critical": Severity.CRITICAL,
    "urgent": Severity.CRITICAL,
    "紧急": Severity.CRITICAL,
}


class DeviceKind(StrEnum):
    """设备类型。取自反无人机现场的四大类设备。"""

    RF_JAM = "无线电电压制设备"
    RF_DETECT = "射频信号侦测设备"
    RADAR_EO = "雷达+视觉设备"
    LASER = "激光设备"
    UNKNOWN = "未知设备"

    @classmethod
    def from_prefix(cls, prefix: str) -> DeviceKind:
        return PREFIX_TO_KIND.get(prefix.upper(), cls.UNKNOWN)


PREFIX_TO_KIND: dict[str, DeviceKind] = {
    "RF-JAM": DeviceKind.RF_JAM,
    "RF-DET": DeviceKind.RF_DETECT,
    "RD-EO": DeviceKind.RADAR_EO,
    "LASER": DeviceKind.LASER,
}


class LogRecord(BaseModel):
    """单条巡检日志的结构化表示。"""

    model_config = ConfigDict(frozen=True)

    timestamp: str
    device_id: str
    device_kind: DeviceKind
    level: str
    message: str
    raw: str

    @field_validator("level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()


class ReportStatistics(BaseModel):
    """由代码计算得出的客观统计（不交给模型，避免幻觉）。"""

    total_lines: int
    parsed_lines: int
    unparsed_lines: int
    # 日志中出现过的设备总数（覆盖范围）
    devices_total: int
    # 存在至少一条问题项的设备数（真正需要处理的范围）
    affected_devices: int
    severity_counts: dict[str, int]
    highest_severity: Severity


class Finding(BaseModel):
    """单台设备的一个问题项，由大模型产出。"""

    device_id: str
    device_kind: DeviceKind = DeviceKind.UNKNOWN
    severity: Severity = Severity.MEDIUM
    title: str = Field(min_length=1, max_length=60)
    detail: str = Field(min_length=1)
    evidence: list[str] = Field(default_factory=list)
    impact: str = ""
    recommendation: str = ""

    @field_validator("severity", mode="before")
    @classmethod
    def _coerce_severity(cls, value: Any) -> Any:
        """容忍模型输出 HIGH / high / 严重 等各种写法。"""
        if value is None:
            return Severity.MEDIUM
        try:
            return Severity.coerce(value)
        except ValueError:
            return Severity.MEDIUM

    @field_validator("device_kind", mode="before")
    @classmethod
    def _coerce_kind(cls, value: Any) -> Any:
        """容忍模型输出 rf_jam / 压制设备 等各种写法。"""
        if isinstance(value, DeviceKind):
            return value
        text = str(value).strip()
        if not text:
            return DeviceKind.UNKNOWN
        for member in DeviceKind:
            if text == member.value or text.upper() == member.name:
                return member
        # 关键字模糊匹配，覆盖"无线电电压制"这类省略写法
        for member in DeviceKind:
            if member is not DeviceKind.UNKNOWN and member.value[:3] in text:
                return member
        return DeviceKind.UNKNOWN


class ReportDraft(BaseModel):
    """大模型的结构化输出 schema。

    模型只允许输出这些字段，且必须通过 Pydantic 校验；
    统计数字不在此列，因为它们由代码计算。
    """

    model_config = ConfigDict(extra="forbid")

    overall_status: Severity = Severity.NORMAL
    executive_summary: str = Field(min_length=1)
    findings: list[Finding] = Field(default_factory=list)
    immediate_actions: list[str] = Field(default_factory=list)
    follow_up_actions: list[str] = Field(default_factory=list)

    @field_validator("overall_status", mode="before")
    @classmethod
    def _coerce_severity(cls, value: Any) -> Any:
        return Severity.coerce(value)

    @field_validator("findings")
    @classmethod
    def _sort_findings(cls, value: list[Finding]) -> list[Finding]:
        return sorted(value, key=lambda f: (-f.severity.rank, f.device_id))


class InspectionReport(BaseModel):
    """最终报告：模型产出 + 代码统计合并而成。"""

    report_date: str
    site: str
    overall_status: Severity
    executive_summary: str
    findings: list[Finding]
    immediate_actions: list[str]
    follow_up_actions: list[str]
    statistics: ReportStatistics

    @field_validator("overall_status", mode="before")
    @classmethod
    def _coerce_severity(cls, value: Any) -> Any:
        return Severity.coerce(value)
