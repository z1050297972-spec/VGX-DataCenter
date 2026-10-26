"""审计领域的 job 对象约束（08 已批准扩展），不反向依赖作业领域或接受任意参数载荷。"""

from rdp.audit.types import OperationDetails, OperationEvent


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
    raise NotImplementedError
