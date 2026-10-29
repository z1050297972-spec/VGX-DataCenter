"""统计遍历的等待与IO优先级（领域层，M1-02），不获取导航锁、不修改主worker优先级。

选择系统ionice -c 3设置专属遍历线程为idle类；os.setpriority仅改变CPU nice，不能保证idle IO类。
调用标准库subprocess且不用shell，不新增Python依赖。每个线程结束即释放该优先级状态。
整个大数据集可运行数分钟；超时约束的是两次元数据访问进展之间的等待，不能套用全树10秒期限。
"""

import logging
import shutil
import subprocess
import time
from collections.abc import Callable
from contextvars import copy_context
from pathlib import Path
from threading import Event, Lock, Thread, get_native_id

from rdp.infra.diagnostics import Diagnostic, DiagnosticCategory, DiagnosticLevel, ExternalError
from rdp.infra.storage import STORAGE_CHECKPOINT_INTERVAL_S, StorageAccessChecker
from rdp.jobs.datasets._size_walk import walk
from rdp.jobs.datasets._sizing_types import SizeValue
from rdp.jobs.datasets._storage_paths import MAX_SYMLINKS, inspect_path, locate_path
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.policy import PROCESS_STDERR_TAIL_MAX_BYTES

logger = logging.getLogger(__name__)

# ionice是本地短命令，五秒仍未结束视为外部失败；不会退回普通IO优先级继续读取。
PRIORITY_TIMEOUT_S = 5.0


def measure(
    path: Path, checker: StorageAccessChecker, context: ExecutionContext
) -> SizeValue | None:
    """在独立低优先级线程遍历；访问停滞返回None，取消原样传播并禁止迟到发布。"""
    completed, abandoned = Event(), Event()
    guard = Lock()
    last = [time.monotonic()]
    result: list[SizeValue | Exception] = []

    def pulse() -> None:
        if abandoned.is_set():
            raise InterruptedError("统计已放弃")
        with guard:
            last[0] = time.monotonic()

    def read() -> None:
        try:
            _idle_priority()
            logger.info(
                "开始低IO优先级统计",
                extra={
                    "fields": {
                        "target": str(path),
                        "native_thread_id": get_native_id(),
                        "io_class": "idle",
                    }
                },
            )
            pulse()
            result.append(walk(_resolve(path, checker, pulse), pulse))
        except Exception as error:
            result.append(error)
        finally:
            completed.set()

    thread = Thread(target=copy_context().run, args=(read,), daemon=True, name="dataset-sizing")
    context.reporter.track_output_thread(thread)
    thread.start()
    try:
        while not completed.wait(STORAGE_CHECKPOINT_INTERVAL_S):
            context.reporter.check_cancelled()
            with guard:
                stalled = time.monotonic() - last[0] >= checker.options.access_timeout_s
            if stalled:
                return None
        context.reporter.check_cancelled()
        value = result[0]
        if isinstance(value, Exception):
            raise value
        return value
    finally:
        abandoned.set()


def _idle_priority() -> None:
    """只设置当前Linux原生线程的IO调度类，不影响并行扫描或其他作业。"""
    try:
        command = shutil.which("ionice")
        if command is None:
            raise OSError("找不到ionice，无法保证最低IO优先级")
        subprocess.run(  # noqa: S603  # 理由：可执行文件来自系统which，参数固定且线程编号只来自内核。
            (command, "-c", "3", "-p", str(get_native_id())),
            check=True,
            capture_output=True,
            text=True,
            timeout=PRIORITY_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="设置统计IO优先级",
                    source="平台",
                    objects=(),
                    rule="SIZING_IO_PRIORITY",
                    actual=_priority_failure(error),
                    expected="ionice成功设置当前遍历线程为idle类",
                    consequence="本次统计失败，不读取数据、不覆盖旧值",
                    next_step="检查ionice是否可用及调用权限后重新提交",
                ),
            )
        ) from error


def _resolve(path: Path, checker: StorageAccessChecker, pulse: Callable[[], None]) -> Path:
    """目标软链接按realpath解析，每次跨根都核对挂载，内部链接则由walk保持不跟随。"""
    for _ in range(MAX_SYMLINKS):
        pulse()
        path = locate_path(path, tuple(root.path for root in checker.mounts.roots))
        root = next((root for root in checker.mounts.roots if path.is_relative_to(root.path)), None)
        if root is None or not checker.check(root.name, checkpoint=pulse).online:
            raise OSError("目标根未登记或离线")
        observed = inspect_path(path, root.path)
        if observed.exists is False:
            raise FileNotFoundError(str(path))
        if observed.exists is True:
            return observed.resolved
        path = observed.resolved
    raise OSError("链接解析超过40跳")


def _priority_failure(error: OSError | subprocess.SubprocessError) -> str:
    """保留固定命令的退出码和有界stderr，不能把完整工具输出无限塞进诊断。"""
    if isinstance(error, subprocess.CalledProcessError):
        stderr: object = error.stderr
        tail = (
            stderr[-PROCESS_STDERR_TAIL_MAX_BYTES:] if isinstance(stderr, str) else "无文本stderr"
        )
        return f"ionice exit_code={error.returncode}; stderr={tail}"
    return f"ionice {type(error).__name__}: {error}"
