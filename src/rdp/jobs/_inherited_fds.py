"""作业线程限定的工具描述符继承；只传显式登记的协调锁，不传 worker 锁。"""

from contextvars import ContextVar

# 每个执行线程独立；仅下载协调锁在持有期间显式设置。
INHERITED_FDS: ContextVar[tuple[int, ...]] = ContextVar("job_inherited_fds", default=())
