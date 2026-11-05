"""报告生成编排。

流程：
    解析日志 -> 调模型产出草稿 -> 事实校验 -> 合并代码统计 -> 渲染

事实校验是这里最重要的一环：模型可能编造不存在的设备编号或凭空造证据，
我们在代码层把它拦下来，并强制把证据回填为日志里的原始行。
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date
from pathlib import Path

from .llm import LLMClient, generate_draft
from .models import (
    Finding,
    InspectionReport,
    LogRecord,
    ReportDraft,
    ReportStatistics,
    Severity,
)
from .parser import estimate_severity, parse_log_text

logger = logging.getLogger(__name__)


def build_statistics(
    records: list[LogRecord], unparsed: list[str], findings: list[Finding]
) -> ReportStatistics:
    """由代码计算客观统计，不采信模型给出的数字。

    注意：统计必须基于**清洗后**的 findings，否则模型幻觉被剔除后，
    分级计数会和最终报告里的问题明细对不上。
    """
    severity_counts = Counter(f.severity.value for f in findings)
    for severity in Severity:
        severity_counts.setdefault(severity.value, 0)

    highest = Severity.NORMAL
    for finding in findings:
        highest = max(highest, finding.severity, key=lambda s: s.rank)

    return ReportStatistics(
        total_lines=len(records) + len(unparsed),
        parsed_lines=len(records),
        unparsed_lines=len(unparsed),
        devices_total=len({r.device_id for r in records}),
        affected_devices=len({f.device_id for f in findings}),
        severity_counts=dict(severity_counts),
        highest_severity=highest,
    )


def validate_findings(
    draft: ReportDraft, records: list[LogRecord]
) -> tuple[list[Finding], list[str]]:
    """校验模型产出的问题项，剔除幻觉并回填真实证据。

    返回 (清洗后的问题项列表, 被剔除项的说明列表)。
    """
    known_devices = {r.device_id: r for r in records}
    cleaned: list[Finding] = []
    rejected: list[str] = []

    for finding in draft.findings:
        if finding.device_id not in known_devices:
            rejected.append(f"{finding.device_id}：日志中不存在该设备，疑似模型虚构，已剔除")
            continue

        real = known_devices[finding.device_id]
        if finding.device_kind.value != real.device_kind.value:
            finding = finding.model_copy(update={"device_kind": real.device_kind})

        # 证据必须来自真实日志：只保留能在日志里找到的原始行
        valid_evidence = [e for e in finding.evidence if e and _evidence_exists(e, records)]
        if not valid_evidence:
            valid_evidence = [r.raw for r in records if r.device_id == finding.device_id][:3]
            if valid_evidence:
                rejected.append(
                    f"{finding.device_id}：模型给出的证据无法在日志中匹配，已替换为该设备的真实日志行"
                )

        cleaned.append(finding.model_copy(update={"evidence": valid_evidence}))

    cleaned.sort(key=lambda f: (-f.severity.rank, f.device_id))
    return cleaned, rejected


def _evidence_exists(evidence: str, records: list[LogRecord]) -> bool:
    """证据行是否真实存在于日志中（允许模型截断时间戳前缀）。"""
    needle = evidence.strip()
    if not needle:
        return False
    return any(needle == record.raw or needle in record.raw for record in records)


def generate_report(
    client: LLMClient,
    log_text: str,
    *,
    site: str = "未指定现场",
    report_date: str | None = None,
) -> InspectionReport:
    """从原始日志文本生成完整报告。"""
    records, unparsed = parse_log_text(log_text)
    if not records:
        raise ValueError("未能从输入中解析出任何巡检记录，请检查日志格式")

    draft = generate_draft(client, records, unparsed, site)
    findings, rejected = validate_findings(draft, records)

    for message in rejected:
        logger.warning("事实校验拦截：%s", message)

    if rejected:
        note = "；".join(rejected)
        draft = draft.model_copy(
            update={
                "executive_summary": f"{draft.executive_summary}\n\n[数据质量提示] {note}",
                "findings": findings,
            }
        )

    statistics = build_statistics(records, unparsed, findings)

    return InspectionReport(
        report_date=report_date or date.today().isoformat(),
        site=site,
        overall_status=draft.overall_status,
        executive_summary=draft.executive_summary,
        findings=findings,
        immediate_actions=draft.immediate_actions,
        follow_up_actions=draft.follow_up_actions,
        statistics=statistics,
    )


def generate_report_from_file(
    client: LLMClient, path: str | Path, *, site: str = "未指定现场"
) -> InspectionReport:
    """从日志文件生成报告。"""
    text = Path(path).read_text(encoding="utf-8")
    return generate_report(client, text, site=site)


def severity_prior_table(records: list[LogRecord]) -> list[tuple[str, Severity]]:
    """按设备汇总先验等级，供 CLI 展示（不进入模型输出）。"""
    per_device: dict[str, Severity] = {}
    for record in records:
        current = per_device.get(record.device_id, Severity.NORMAL)
        per_device[record.device_id] = max(current, estimate_severity(record), key=lambda s: s.rank)
    return sorted(per_device.items(), key=lambda item: -item[1].rank)
