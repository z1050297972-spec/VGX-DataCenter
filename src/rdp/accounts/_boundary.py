"""账号领域异常出口：保留安全类别和定位，隔离驱动可能回显的秘密（规范 6.10）。

基础数据库工作单元按第 5 张保留原始异常链；账号领域不能把它交给完整报告器。
使用标准库 wraps/traceback 保留签名和不含源码、局部变量的定位，不记录日志。
"""

import traceback
from collections.abc import Callable
from functools import wraps

from rdp.audit.policy import AUDIT_APPEND_FAILED
from rdp.infra.diagnostics import ConflictError, DefectError, ExternalError, InputError

# 只保留数据库固定清理提示和审计补记的固定标记，不能复制驱动附带的任意 notes。
_CLEANUP_NOTES = frozenset(
    {
        "数据库回滚失败，结果未知；请检查数据库与备份。",
        "数据库关闭失败，结果未知；请检查数据库与备份。",
        "数据库连接失效处理也失败，结果未知；请检查数据库与备份。",
        # 07 的失败补记不掩盖原异常；只保留固定标记供 API/ops 边界额外记 ERROR。
        AUDIT_APPEND_FAILED,
    }
)


def protect[**P, R](function: Callable[P, R]) -> Callable[P, R]:
    """所有账号服务操作共用安全出口，非 Exception 的取消控制流保持原样。"""

    @wraps(function)
    def guarded(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return function(*args, **kwargs)
        except Exception as error:
            safe = _safe_error(error)
        # 离开 except 后再抛，避免 Python 自动把含秘密的原异常重新挂为 context。
        raise safe

    return guarded


def _safe_error(error: Exception) -> Exception:
    """可信类别和诊断由领域构造；外部消息、链、源码行及任意 notes 都不外泄。"""
    safe = (
        error
        if isinstance(error, (InputError, ConflictError, ExternalError, DefectError))
        else DefectError()
    )
    notes = [note for note in getattr(error, "__notes__", ()) if note in _CLEANUP_NOTES]
    locations = [
        f"{frame.f_code.co_filename}:{line} {frame.f_code.co_name}"
        for frame, line in traceback.walk_tb(error.__traceback__)
    ][-20:]
    safe.__traceback__ = None
    safe.__cause__ = None
    safe.__context__ = None
    safe.__suppress_context__ = True
    safe.__notes__ = [*notes, *(("定位：" + " | ".join(locations),) if locations else ())]
    return safe
