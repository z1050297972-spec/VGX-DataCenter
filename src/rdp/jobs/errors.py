"""作业输入、查无记录及协作停止信号；沿用规范 6.2 四类异常，不另建失败体系。"""

from http import HTTPStatus
from typing import ClassVar

from rdp.infra.diagnostics import ConflictError, InputError


class JobInputError(InputError):
    """参数、筛选或游标不合法；安全诊断不回显拒绝值。"""

    http_status: ClassVar[HTTPStatus] = HTTPStatus.UNPROCESSABLE_ENTITY


class JobNotFoundError(InputError):
    """指定作业编号不存在；不是尚未产生作业日志。"""

    http_status: ClassVar[HTTPStatus] = HTTPStatus.NOT_FOUND


class JobCancelledError(ConflictError):
    """执行上下文的协作取消控制信号，由执行器专门捕获而不按作业失败报告，不向 HTTP 传播。"""


class WorkerStoppingError(ConflictError):
    """进程内停止控制信号；不把运行中作业写成已取消或已完成。"""
