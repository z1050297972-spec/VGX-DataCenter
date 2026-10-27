"""审计领域的 job 对象约束（08 已批准扩展），不反向依赖作业领域或接受任意参数载荷。"""

import re

from rdp.audit.errors import AuditInputError
from rdp.audit.types import OperationDetails, OperationEvent, OperationResult, OperationType
from rdp.infra.db.validation import invalid_field
from rdp.infra.ids import JOB_TYPE_KEY_PATTERN, MAX_SQLITE_INTEGER


def validate_job_operation(event: OperationEvent, details: OperationDetails) -> None:
    """核对作业对象、操作类型与 v1 白名单明细之间的一致性。

    Args:
        event: 已通过共同上下文、身份、对象编号形状和结果类别校验的事件。
        details: 按对应操作白名单校验过的 before/after，值不可含秘密。

    Returns:
        无；提交和取消的对象必须为 job，其他操作不能借用 job 对象。
        成功提交 before 为空，after 为新作业编号/类型/queued，可加 resubmitted_from；
        成功取消 before/after 的编号/类型相同，状态是 queued→cancelled 或 running→cancelling。
        失败 after 为空，保留已确认的 before，未分配新编号时对象编号可空、名字固定“新作业”。

    Raises:
        AuditInputError: 操作/对象不匹配、非规范或越界编号、明细与对象编号不一致、
            状态组合非法、对象名超过 64 码点或重新提交来源出现在取消明细。

    Side Effects:
        无；不生成作业编号、不查询作业或账号、不修改明细，不在诊断回显拒绝值。

    Time Semantics:
        同步校验；不计算作业状态，不读时钟或执行事务，字段状态仅校验已知审计事件形状。
    """
    allowed = {OperationType.SUBMIT_JOB, OperationType.CANCEL_JOB}
    if event.target.kind != "job" or event.operation not in allowed:
        raise AuditInputError(invalid_field("job_operation", "作业操作与作业对象一致").diagnostics)
    before, after = details.before, details.after
    if event.result is OperationResult.FAILURE:
        valid = not after.model_dump(exclude_none=True)
        if event.target.object_id is None:
            valid = (
                valid
                and event.operation is OperationType.SUBMIT_JOB
                and event.target.name == "新作业"
                and not before.model_dump(exclude_none=True)
            )
        else:
            valid = valid and _identity(before.job_id, before.job_type, event.target.object_id)
            valid = (
                valid
                and event.operation is OperationType.CANCEL_JOB
                and before.job_state in {"queued", "running"}
                and before.resubmitted_from is None
            )
    elif event.operation is OperationType.SUBMIT_JOB:
        valid = (
            not before.model_dump(exclude_none=True)
            and _identity(after.job_id, after.job_type, event.target.object_id)
            and after.job_state == "queued"
        )
        valid = valid and (after.resubmitted_from is None or _number(after.resubmitted_from))
    else:
        valid = _identity(before.job_id, before.job_type, event.target.object_id) and _identity(
            after.job_id, after.job_type, event.target.object_id
        )
        valid = (
            valid
            and before.job_type == after.job_type
            and (before.job_state, after.job_state)
            in {("queued", "cancelled"), ("running", "cancelling")}
        )
        valid = valid and before.resubmitted_from is None and after.resubmitted_from is None
    if not valid or not 1 <= len(event.target.name) <= 64:
        raise AuditInputError(
            invalid_field("job_operation", "合法的作业编号、类型和前后状态明细").diagnostics
        )


def _number(value: str | None) -> bool:
    """规范十进制正编号，不接受前导零、Unicode数字或SQLite范围外值。"""
    return (
        value is not None
        and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None
        and int(value) <= MAX_SQLITE_INTEGER
    )


def _identity(identifier: str | None, type_name: str | None, target: str | None) -> bool:
    """审计只验证稳定键的形状，不反向查询作业登记表。"""
    return (
        _number(identifier)
        and identifier == target
        and type_name is not None
        and re.fullmatch(JOB_TYPE_KEY_PATTERN, type_name) is not None
    )
