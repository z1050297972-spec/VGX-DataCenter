"""作业ORM到领域快照的内部转换；使用Pydantic解码JSON，不返回懒加载对象或共享可变参数。"""

import json
import math
from copy import deepcopy
from typing import cast

from pydantic import TypeAdapter

from rdp.infra.actors import ActorRef
from rdp.infra.diagnostics import (
    DIAGNOSTIC_SAMPLE_LIMIT,
    DefectError,
    DiagnosticCategory,
    DiagnosticGroup,
    InputError,
)
from rdp.jobs import _storage
from rdp.jobs.models import JobRow
from rdp.jobs.policy import (
    JOB_ARTIFACT_LIMIT,
    JOB_ARTIFACT_MAX_CHARS,
    JOB_DIAGNOSTIC_GROUP_LIMIT,
    JOB_DIAGNOSTIC_OVERFLOW_KEY,
    JOB_PARAMETERS_MAX_BYTES,
    JOB_RECOVERY_LIMIT,
)
from rdp.jobs.types import (
    ExecutionSnapshot,
    JobProgress,
    JobRecord,
    JobState,
    JobSummary,
    RecoveryMode,
    WaitReason,
)

# TypeAdapter只缓存类型编译结果，不持有作业/账号数据，复用统一值对象而不重复手写JSON结构。
_SNAPSHOT = TypeAdapter(ExecutionSnapshot)
_SUMMARY = TypeAdapter(JobSummary)
_GROUPS = TypeAdapter(tuple[DiagnosticGroup, ...])


def record(row: JobRow) -> JobRecord:
    """冻结行内容，参数深拷贝避免调用者改动会话中的同一个字典。"""
    _validate_parameters(row)
    try:
        state, mode = JobState(row.state), RecoveryMode(row.recovery_mode)
        waiting = None if row.wait_reason is None else WaitReason(row.wait_reason)
    except (ValueError, TypeError):
        raise DefectError() from None
    result = JobRecord(
        job_id=row.job_id,
        type_name=row.type_name,
        display_name=row.display_name,
        parameters=deepcopy(row.parameters),
        submitted_by=ActorRef(row.submitter_id, row.submitter_name),
        submitter_deleted=False,
        submitted_at=row.submitted_at,
        resubmitted_from=row.resubmitted_from,
        state=state,
        started_at=row.started_at,
        ended_at=row.ended_at,
        progress=None if row.progress is None else _decode(TypeAdapter(JobProgress), row.progress),
        progress_at=row.progress_at,
        elapsed_s=row.elapsed_s,
        artifacts=tuple(row.artifacts),
        tool_exit_code=row.tool_exit_code,
        log_path=row.log_path,
        summary=None if row.summary is None else _decode(_SUMMARY, row.summary),
        diagnostics=_decode(_GROUPS, row.diagnostics),
        recovery_mode=mode,
        recovery_count=row.recovery_count,
        gpu_index=row.gpu_index,
        wait_reason=waiting,
        holds_navigation_lock=row.holds_navigation_lock,
    )

    _validate_record(row, result)
    return result


def summary_data(value: JobSummary) -> dict[str, object]:
    """摘要只序列化同一个冻结值对象，不重新计算结果或转换计数口径。"""
    return cast(dict[str, object], _SUMMARY.dump_python(value, mode="json"))


def _decode[T](adapter: TypeAdapter[T], value: object) -> T:
    """严格解码存量JSON值；JSON中的枚举文本可用，数字字符串不能冒充计数。"""
    try:
        return adapter.validate_json(
            json.dumps(value, ensure_ascii=False, allow_nan=False), strict=True
        )
    except (TypeError, ValueError, UnicodeError):
        raise DefectError() from None


def _validate_parameters(row: JobRow) -> None:
    """参数必须仍是有界JSON对象；拒绝损坏内容而不把原文带入异常链。"""
    try:
        valid = (
            isinstance(cast(object, row.parameters), dict)
            and len(json.dumps(row.parameters, ensure_ascii=False, allow_nan=False).encode())
            <= JOB_PARAMETERS_MAX_BYTES
        )
    except (TypeError, ValueError, UnicodeError):
        valid = False
    if not valid:
        raise InputError(
            (_storage.diagnostic(row.job_id, "作业参数JSON损坏", DiagnosticCategory.INPUT),)
        )


def _validate_record(row: JobRow, record: JobRecord) -> None:
    """核对独立计数、生命周期和摘要，查询不可把损坏的行当成合法状态展示。"""
    counters = (row.total_items, row.failed_items, row.warning_count)
    reported = (
        (0, 0, 0)
        if record.progress is None
        else (
            record.progress.total_items,
            record.progress.failed_items,
            record.progress.warning_count,
        )
    )
    if counters != reported or any(type(value) is not int or value < 0 for value in counters):
        raise DefectError()
    if type(row.elapsed_s) not in {int, float} or type(row.recovery_count) is not int:
        raise DefectError()
    if (
        not math.isfinite(row.elapsed_s)
        or row.elapsed_s < 0
        or not 0 <= row.recovery_count <= JOB_RECOVERY_LIMIT
    ):
        raise DefectError()
    terminal = record.state in {JobState.COMPLETED, JobState.CANCELLED, JobState.INTERRUPTED}
    if terminal != (record.summary is not None) or terminal != (row.ended_at is not None):
        raise DefectError()
    if record.state in {
        JobState.RUNNING,
        JobState.CANCELLING,
        JobState.COMPLETED,
        JobState.INTERRUPTED,
    } and (row.started_at is None or row.log_path is None):
        raise DefectError()
    if record.state is JobState.QUEUED and (row.started_at is not None or row.log_path is not None):
        raise DefectError()
    if (record.state is JobState.COMPLETED) != (row.outcome is not None):
        raise DefectError()
    _validate_groups(record.diagnostics)
    if record.summary is not None:
        _validate_summary(row, record.summary, record)


def _validate_summary(row: JobRow, summary: JobSummary, record: JobRecord) -> None:
    """摘要与同一行的每项字段必须一致，不调用结果计算器重写旧结论。"""
    actual = (
        summary.state,
        summary.outcome,
        summary.progress,
        summary.total_items,
        summary.failed_items,
        summary.warning_count,
        summary.aborted,
        summary.elapsed_s,
        summary.artifacts,
        summary.tool_exit_code,
    )
    expected = (
        record.state,
        row.outcome,
        record.progress,
        row.total_items,
        row.failed_items,
        row.warning_count,
        row.aborted,
        row.elapsed_s,
        record.artifacts,
        row.tool_exit_code,
    )
    if actual != expected:
        raise DefectError()


def snapshot_data(value: ExecutionSnapshot) -> tuple[ExecutionSnapshot, dict[str, object]]:
    """重新校验冻结快照再编码，不能让model_construct或可变的嵌套输入绕过进度校验。"""
    try:
        encoded = _SNAPSHOT.dump_python(value, mode="json", warnings="error")
        checked = _decode(_SNAPSHOT, encoded)
    except Exception:
        raise DefectError() from None
    if not math.isfinite(checked.elapsed_s) or checked.elapsed_s < 0:
        raise DefectError()
    if len(checked.artifacts) > JOB_ARTIFACT_LIMIT or any(
        not item or len(item) > JOB_ARTIFACT_MAX_CHARS for item in checked.artifacts
    ):
        raise DefectError()
    if len(checked.diagnostics) > JOB_DIAGNOSTIC_GROUP_LIMIT + 1:
        raise DefectError()
    _validate_groups(checked.diagnostics)
    return checked, cast(dict[str, object], encoded)


def _validate_groups(groups: tuple[DiagnosticGroup, ...]) -> None:
    """聚合总数保留完整口径，样例只保留前N条，不能用重复组或错来源混淆计数。"""
    if len(groups) > JOB_DIAGNOSTIC_GROUP_LIMIT + 1:
        raise DefectError()
    seen: set[tuple[str, str]] = set()
    for group in groups:
        key = group.source, group.rule
        if not group.source.strip() or not group.rule.strip() or key in seen:
            raise DefectError()
        seen.add(key)
        if (
            group.total <= 0
            or min(group.error_count, group.warning_count) < 0
            or group.total != group.error_count + group.warning_count
        ):
            raise DefectError()
        if len(group.samples) != min(group.total, DIAGNOSTIC_SAMPLE_LIMIT):
            raise DefectError()
        if key != JOB_DIAGNOSTIC_OVERFLOW_KEY and any(
            (sample.source, sample.rule) != key for sample in group.samples
        ):
            raise DefectError()
    if len(seen - {JOB_DIAGNOSTIC_OVERFLOW_KEY}) > JOB_DIAGNOSTIC_GROUP_LIMIT:
        raise DefectError()
