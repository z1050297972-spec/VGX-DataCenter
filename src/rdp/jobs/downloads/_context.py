"""为同一执行线程的受管适配器绑定作业上下文；不跨任务共享信号。"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from contextvars import ContextVar

from rdp.infra.diagnostics import DefectError
from rdp.jobs.execution import ExecutionContext

# ContextVar 在线程和异步上下文之间隔离，避免进程级单例混淆并发作业。
_CURRENT: ContextVar[ExecutionContext | None] = ContextVar("download_execution", default=None)
_RECHECK: ContextVar[Callable[[], None] | None] = ContextVar("download_recheck", default=None)
_ADJUST: ContextVar[Callable[[], object | None] | None] = ContextVar(
    "download_adjust", default=None
)


@contextmanager
def bind(
    context: ExecutionContext,
    recheck: Callable[[], None] | None = None,
    adjust: Callable[[], object | None] | None = None,
) -> Generator[None]:
    """限定实际工具访问当前作业信号的时间范围。"""
    token = _CURRENT.set(context)
    recheck_token = _RECHECK.set(recheck)
    adjust_token = _ADJUST.set(adjust)
    try:
        yield
    finally:
        _ADJUST.reset(adjust_token)
        _RECHECK.reset(recheck_token)
        _CURRENT.reset(token)


def current() -> ExecutionContext:
    """返回本执行上下文；缺失时拒绝无监管的子进程。"""
    context = _CURRENT.get()
    if context is None:
        raise DefectError()
    return context


def recheck() -> None:
    """执行当前作业的周期镜像检查；独立适配器调用时可无回调。"""
    callback = _RECHECK.get()
    if callback is not None:
        callback()


def adjustment() -> object | None:
    """检查 curl 运行期间是否需要应用新的速率。"""
    callback = _ADJUST.get()
    return callback() if callback is not None else None
