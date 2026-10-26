"""运维入口的日志补记故障报告契约（07），不依赖 API、不写两种日志表。

报告仅供创建首管理员及运维重置的最外层异常边界使用，不供领域层调用。
固定标记由 accounts._boundary 保留，任意异常 notes 和第二异常原文不能穿过脱敏边界。
"""


def report_audit_append_failure(error: Exception) -> None:
    """在运维命令最外层额外报告失败日志无法追加的故障。

    Args:
        error: 原业务异常，仅检查 policy.AUDIT_APPEND_FAILED 固定标记，不格式化任意 notes。

    Returns:
        无；标记存在时只记一次 ERROR，没有标记不记录，原异常类别和命令退出结果保持不变。

    Raises:
        无；报告器自身失败也不能替换原业务异常。

    Side Effects:
        仅运行日志，不连接数据库、不递归追加、不读取凭据或打印异常原文；运维没有请求编号。
        只消耗固定标记以保证重复调用幂等，原异常类别及诊断不变。

    Time Semantics:
        在业务回滚及补记尝试均结束后同步报告，无网络/数据库等待或重试。
    """
    raise NotImplementedError
