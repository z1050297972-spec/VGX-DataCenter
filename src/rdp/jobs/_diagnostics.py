"""作业内的有界增量诊断聚合；使用已有DiagnosticGroup格式，流式追加不能重算旧样例的完整总数。"""

from dataclasses import replace

from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    Diagnostic,
    DiagnosticGroup,
    DiagnosticLevel,
)
from rdp.jobs.policy import JOB_DIAGNOSTIC_GROUP_LIMIT, JOB_DIAGNOSTIC_OVERFLOW_KEY


def append(
    groups: tuple[DiagnosticGroup, ...], diagnostic: Diagnostic
) -> tuple[DiagnosticGroup, ...]:
    """只保留前N样例与完整总数，规则数超限时保留原身份进入唯一溢出组。"""
    collected = {(group.source, group.rule): group for group in groups}
    key = (diagnostic.source, diagnostic.rule)
    if key not in collected and len(collected) >= JOB_DIAGNOSTIC_GROUP_LIMIT:
        key = JOB_DIAGNOSTIC_OVERFLOW_KEY
    group = collected.get(key, DiagnosticGroup(*key, 0, 0, 0, ()))
    samples = group.samples
    if len(samples) < DIAGNOSTIC_SAMPLE_LIMIT:
        samples += (diagnostic,)
    collected[key] = replace(
        group,
        total=group.total + 1,
        error_count=group.error_count + (diagnostic.level is DiagnosticLevel.ERROR),
        warning_count=group.warning_count + (diagnostic.level is DiagnosticLevel.WARNING),
        samples=samples,
    )
    return tuple(collected.values())
