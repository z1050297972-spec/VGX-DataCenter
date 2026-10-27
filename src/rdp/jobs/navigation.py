"""导航层写锁执行边界（领域层，ADR 0005）；锁在 worker 实例内，不是模块单例。

标准库 threading.Lock 提供互斥；框架只控制顺序，预览核对与实际写入由作业类型提供。
"""

from collections.abc import Callable, Generator
from contextlib import contextmanager
from threading import Lock, get_ident
from typing import cast

from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
)
from rdp.jobs import _storage, policy
from rdp.jobs._clock import ClockReader
from rdp.jobs.progress import ProgressReporter
from rdp.jobs.scheduling_types import ResourceDisplay
from rdp.jobs.types import WaitReason


class NavigationWriter:
    """整个导航层共用的一把非可重入锁，执行上下文由 worker 注入同一对象。"""

    def __init__(self) -> None:
        """构造一个尚无人持有的导航层写锁。

        Args:
            无。

        Returns:
            无；每次构造互相隔离，worker 仅构造一次。

        Raises:
            无。

        Side Effects:
            只建立进程内 Lock；不创建文件锁、不访问导航层或数据库。

        Time Semantics:
            在线程启动之前调用，崩溃后内存锁随进程消失。
        """
        self._lock = Lock()
        self._owner_lock = Lock()
        self._owner: tuple[int, int] | None = None

    def run[T](
        self,
        reporter: ProgressReporter,
        verify: Callable[[], None],
        write: Callable[[], T],
    ) -> T:
        """拿锁后核对预览状态，只有核对通过才调用写入。

        Args:
            reporter: 当前作业的上报/取消及资源副本对象，关联唯一 job_id。
            verify: 同步无参数核对；不改业务数据，冲突抛 ConflictError，诊断由类型查明最后修改者 #N。
            write: 同步无参数写入；返回任意类型 T，不可递归取锁，不可启动异步写入后提前返回。
                每个阻塞操作有界，持锁段应能在 worker 三十秒共同停止预算内完成。

        Returns:
            write 的原返回值；核对失败或等待取消时 write 一次也不会调用。

        Raises:
            JobCancelledError: 等锁前/期间或拿锁后进入保护区前收到取消；保护区内延后至放锁后的下一检查点。
            WorkerStoppingError: 等锁期间或进入保护区前停止；持锁期间同样延后，不能中断半次写入。
            ConflictError: 达到 NAVIGATION_LOCK_TIMEOUT_S=300 秒仍未获得锁，诊断包含当前作业编号、
                单调累计实际等待秒数、超时时观察到的持锁作业编号（释放竞争时明确无人持有）、
                等待上限、未执行写入的后果及下一步；或 verify 判定预览已失效。
            ExternalError: 回调中的外部写入、资源展示或日志出现不可跳过的 I/O 失败。
            InputError: 回调拒绝业务输入或资源存储损坏。
            DefectError: 嵌套取锁、非法回调/依赖，或回调其他异常；原异常交执行器收口，不在此重复报告。

        Side Effects:
            锁内维护持有人 job_id，取得后登记、finally 释放时清空；超时身份来自实例内存，不信任滞后数据库副本。
            顺序为设置等待原因→有界分段拿锁→清等待并标持锁→verify→write→finally 放锁并清持锁。
            资源副本短锁忙只延后补写；不能为显示等待持有数据库事务或阻塞调度。
            持锁段通过 reporter.defer_cancellation 屏蔽人为取消及停止控制异常；普通异常照常传播。
            verify 或 write 抛异常、worker 停止时均 finally 释放；清副本失败不能阻止释放或掩盖原异常。
            不自动回滚 write 已产生的产物，其失败残留由类型契约约束；不在放锁时主动检查取消以免掩盖写入异常。
            只保护本次调用显式捕获的主异常；正常写完后的清理故障照常传播，不给调用方正在处理的无关异常加备注。

        Time Semantics:
            每次 acquire 最多 NAVIGATION_LOCK_POLL_S=0.05 秒，总等待最多 300 秒，使用注入单调时钟。
            等待期间补写进度和资源；持锁期间上报仍可运行，取消信号保留不清除，下一检查点才响应。
            线程不协作导致超出停止预算时，worker 单实例锁按第 8 张保留到进程退出，不提前宣称导航锁已释放。
        """
        if (
            not isinstance(cast(object, reporter), ProgressReporter)
            or not callable(verify)
            or not callable(write)
        ):
            raise DefectError()
        _storage.identifier(reporter.job_id, internal=True)
        with self._owner_guard():
            if self._owner is not None and self._owner[0] == get_ident():
                raise DefectError()
        self._acquire(reporter)
        owned = True
        primary: BaseException | None = None
        try:
            reporter.check_cancelled()
            with reporter.defer_cancellation():
                try:
                    reporter.set_resource_display(ResourceDisplay(None, True))
                    verify()
                    return write()
                except BaseException as error:
                    primary = error
                    raise
                finally:
                    owned = False
                    self._finish_release(reporter, primary)
        except BaseException as error:
            primary = error
            raise
        finally:
            if owned:
                self._finish_release(reporter, primary)

    def _acquire(self, reporter: ProgressReporter) -> None:
        """只分段等待，取消和到期补写都在每次拿锁尝试之前检查。"""
        reader = ClockReader(reporter.clock)
        started = reader.read()
        deadline = started + policy.NAVIGATION_LOCK_TIMEOUT_S
        acquired = False
        try:
            reporter.check_cancelled()
            reporter.set_resource_display(ResourceDisplay(WaitReason.NAVIGATION_LOCK, False))
            while True:
                reporter.check_cancelled()
                now = reader.read()
                remaining = deadline - now
                if remaining <= 0:
                    raise self._timeout(reporter.job_id, now - started)
                if self._lock.acquire(timeout=min(policy.NAVIGATION_LOCK_POLL_S, remaining)):
                    acquired = True
                    with self._owner_guard():
                        self._owner = (get_ident(), reporter.job_id)
                    return
        except BaseException as error:
            if acquired:
                self._lock.release()
            _clear_display(reporter, error)
            raise

    def _finish_release(self, reporter: ProgressReporter, primary: BaseException | None) -> None:
        """释放只尝试一次；持有人清理和展示清理的故障都不能替换业务原异常。"""
        cleanup_primary = primary
        try:
            self._release()
        except BaseException as error:
            if cleanup_primary is None:
                cleanup_primary = error
                raise
            cleanup_primary.add_note("导航锁已释放，持有人信息清理失败")
        finally:
            _clear_display(reporter, cleanup_primary)

    def _release(self) -> None:
        """所有异常路径都释放实际写锁，持有人元数据故障不能令锁永久占用。"""
        try:
            with self._owner_guard():
                self._owner = None
        finally:
            self._lock.release()

    @contextmanager
    def _owner_guard(self) -> Generator[None]:
        """持有人信息只在无I/O的小临界区读写，超时读取不依赖滞后数据库。"""
        if not self._owner_lock.acquire(timeout=policy.NAVIGATION_LOCK_POLL_S):
            raise DefectError()
        try:
            yield
        finally:
            self._owner_lock.release()

    def _timeout(self, job_id: int, elapsed_s: float) -> ConflictError:
        """超时诊断记录这一刻观察到的内存持有者和实际单调等待时长。"""
        with self._owner_guard():
            holder = None if self._owner is None else self._owner[1]
        return ConflictError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.CONFLICT,
                    stage="等待导航层写锁",
                    source="平台",
                    objects=(
                        DiagnosticObject(key="job_id", value=str(job_id)),
                        DiagnosticObject(
                            key="holder_job_id", value="无人持有" if holder is None else str(holder)
                        ),
                    ),
                    rule="导航层写锁等待不得超过上限",
                    actual=f"已等待{elapsed_s:.6f}秒；当前持有者：{'无人持有' if holder is None else '#' + str(holder)}",
                    expected=f"在{policy.NAVIGATION_LOCK_TIMEOUT_S:g}秒内获得写锁",
                    consequence="本作业未调用核对或写入函数",
                    next_step="检查持锁作业进度，必要时取消或处理后重新提交",
                ),
            )
        )


def _clear_display(reporter: ProgressReporter, primary: BaseException | None) -> None:
    """清空副本失败时保留回调原异常；实际锁已释放，终态事务仍会强制清空。"""
    try:
        reporter.set_resource_display(ResourceDisplay(None, False))
    except Exception:
        if primary is None:
            raise
        primary.add_note("导航锁已释放，资源展示清空失败，终态事务需强制清空")
