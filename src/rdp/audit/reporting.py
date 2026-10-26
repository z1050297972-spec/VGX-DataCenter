"""日志补记失败的共用报告器（07/6.3），仅由 API、运维等最外层异常边界调用。

账号领域只携带白名单标记，不直接调用报告器；这里不写日志表或依赖其他领域、入口模块。
统一消费通用及登录种类标记，既区分文案，又防止嵌套边界重复记录或泄漏第二异常。
"""

import logging

from rdp.audit.policy import AUDIT_APPEND_FAILED, LOGIN_AUDIT_APPEND_FAILED

logger = logging.getLogger(__name__)


# 固定标记及文案完全由平台定义；不能用任意异常 notes 或原文决定输出。
_APPEND_FAILURE_MARKERS = frozenset({AUDIT_APPEND_FAILED, LOGIN_AUDIT_APPEND_FAILED})
_FAILURE_MESSAGES = {"operation": "操作日志补记失败", "login": "登录日志补记失败"}


def report_audit_append_failure(error: Exception) -> None:
    """在最外层异常边界按日志种类报告一次补记失败，保持原业务错误。

    Args:
        error: 原业务异常；仅识别通用及登录补记失败的固定标记，不格式化其他 notes。

    Returns:
        无；有标记时记录一次 ERROR，无标记不记录；原异常身份、类别、诊断和响应保持不变。

    Raises:
        无；运行日志报告失败也不能掩盖原业务错误。

    Side Effects:
        仅写运行日志，不写两种日志表或递归补记；登录标记输出“登录日志补记失败”，
        仅通用标记输出“操作日志补记失败”。使用模块 logger 和既有请求上下文；
        先消耗全部固定标记保证重复调用幂等，其他 notes 保留但不输出，无秘密或第二异常链。

    Time Semantics:
        在业务回滚及补记尝试结束后的边界同步调用，不新增数据库/网络等待或重试。
    """
    try:
        notes = getattr(error, "__notes__", ())
        if not any(note in _APPEND_FAILURE_MARKERS for note in notes):
            return
        kind = "login" if LOGIN_AUDIT_APPEND_FAILED in notes else "operation"
        # 消耗早于日志调用，handler 失败也不会让外层重复报告；任意其他注释不格式化。
        error.__notes__ = [note for note in notes if note not in _APPEND_FAILURE_MARKERS]
        logger.error(
            _FAILURE_MESSAGES[kind], extra={"fields": {"failure": "audit_append", "log_kind": kind}}
        )
    except Exception:
        # 报告器仅补上下文；磁盘或 handler 故障不能替换正在返回的业务异常。
        return
