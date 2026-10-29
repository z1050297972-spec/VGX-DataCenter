"""worker循环内部边界；每作业独立监视，恢复准备不拿资源，所有线程共用停止截止。"""

import logging
import time
from contextvars import copy_context
from dataclasses import dataclass, replace
from threading import Event, Lock, Thread

from sqlalchemy import select

from rdp.infra.db.connection import session_scope, session_scope_with_lock_timeout
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
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job, recover_job
from rdp.jobs.models import JobRow
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import find_job, return_unstarted_job, save_heartbeat
from rdp.jobs.scheduling import Scheduler
from rdp.jobs.types import JobState, WorkerHeartbeat
from rdp.jobs.worker import WorkerLoopResult

logger = logging.getLogger(__name__)


@dataclass
class _Running:
    """一个已启动作业的独立生命周期。

    Attributes:
        work: 已提交领取记录和本实例凭据。
        monitor: 只包含本作业执行及输出线程。
        signals: 独立取消Event，停止Event由本实例共享。
        thread: 启动前登记的daemon执行线程。
        cancel_seen: 本实例首次观察取消的单调秒数；尚未取消为None。
        cancel_warned: 是否已经报告一次取消超时。
    """

    work: ExecutionWork
    monitor: ExecutionMonitor
    signals: ExecutionSignals
    thread: Thread
    cancel_seen: float | None = None
    cancel_warned: bool = False


class Loop:
    """一次worker实例的执行集合，终态持久化失败后整个实例停止领取和心跳。"""

    def __init__(
        self, dependencies: ExecutorDependencies, stop: Event, heartbeat: WorkerHeartbeat
    ) -> None:
        """保存依赖并验证注入时钟；执行集合只由当前主线程维护。"""
        if dependencies.resources is None:
            raise DefectError()
        self.dependencies, self.stop, self.heartbeat = dependencies, stop, heartbeat
        self.resources = dependencies.resources
        self.clock = ClockReader(dependencies.clock)
        self.next_heartbeat = self.clock.read()
        self.running: dict[int, _Running] = {}
        self.failed = False
        self.execution_failed = Event()
        self.scheduler: Scheduler | None = None
        self._unstarted: ExecutionWork | None = None

    def run(self) -> WorkerLoopResult:
        """先完成全部恢复准备，再循环观察、定时检查和按类型领取。"""
        try:
            self._prepare()
            while not self.stop.is_set():
                if self.execution_failed.is_set():
                    self.failed = True
                    break
                self._heartbeat()
                for running in tuple(self.running.values()):
                    self._observe(running)
                if self.failed:
                    break
                if self.scheduler is None:
                    raise DefectError()
                self.scheduler.tick_schedules()
                if self.stop.is_set():
                    break
                if self.dependencies.poll_submissions is not None:
                    # 恢复准备已经完成；资源不足也不能阻止自动提交，执行仍由原调度器领取。
                    self.dependencies.poll_submissions()
                self._fill()
                self.stop.wait(policy.WORKER_POLL_INTERVAL_S)
        except Exception:
            self.failed = True
            logger.error("worker主循环失败，停止领取及心跳", exc_info=True)
        return self._shutdown()

    def _prepare(self) -> None:
        """逐编号准备所有遗留行，不受资源池容量约束；准备期间也更新心跳。"""
        cursor = 0
        recovered: list[ExecutionWork] = []
        while not self.stop.is_set():
            self._heartbeat()
            with session_scope(self.dependencies.engine, read_only=True) as session:
                number = session.scalar(
                    select(JobRow.job_id)
                    .where(
                        JobRow.job_id > cursor,
                        JobRow.state.in_((JobState.RUNNING.value, JobState.CANCELLING.value)),
                    )
                    .order_by(JobRow.job_id)
                    .limit(1)
                )
            if number is None:
                break
            cursor = number
            work = recover_job(number, self.dependencies)
            if work is not None:
                recovered.append(work)
        self.scheduler = Scheduler(self.dependencies, self.resources, recovered=tuple(recovered))

    def _fill(self) -> None:
        """至多填满声明容量的线程槽，快作业也不能令本轮永远停在领取循环。"""
        if self.scheduler is None:
            raise DefectError()
        # 加一是未登记类型的唯一诊断槽；已结束但尚未观察的线程也先占槽，下一轮再回收。
        capacity = (
            sum(item.concurrency for item in self.resources.configuration.catalog.settings.types)
            + 1
        )
        for _ in range(max(0, capacity - len(self.running))):
            if self.stop.is_set() or self.execution_failed.is_set():
                return
            work = self.scheduler.claim_next()
            if work is None:
                return
            self._unstarted = work
            if self.stop.is_set() or self.execution_failed.is_set():
                self._return_unstarted(work)
                return
            self._start(work)

    def _heartbeat(self) -> None:
        """入场短锁忙只跳过本次，不把入场后的失败当作正常在线。"""
        now = self.clock.read()
        if now < self.next_heartbeat:
            return
        self.next_heartbeat = now + policy.HEARTBEAT_INTERVAL_S
        entered = False
        try:
            with session_scope_with_lock_timeout(
                self.dependencies.engine, busy_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
            ) as session:
                entered = True
                save_heartbeat(
                    session, replace(self.heartbeat, last_seen_at=self.dependencies.clock.now())
                )
        except ConflictError as error:
            if not entered and _storage.entry_busy(error):
                logger.warning("worker心跳写锁忙，本次心跳未更新，下周期重试")
                return
            raise

    def _start(self, work: ExecutionWork) -> None:
        """先登记再启动；只有确认线程从未启动的失败才退回领取，已经启动的线程交停止收尾。"""
        thread: Thread | None = None
        try:
            monitor = ExecutionMonitor([], None, Lock())
            signals = ExecutionSignals(Event(), self.stop, monitor)
            thread = Thread(
                target=copy_context().run, args=(self._execute, work, signals), daemon=True
            )
            running = _Running(work, monitor, signals, thread)
            monitor.threads.append(thread)
            self.running[work.record.job_id] = running
            thread.start()
        except BaseException:
            if thread is None or thread.ident is None:
                self.running.pop(work.record.job_id, None)
                self._return_unstarted(work)
            else:
                # start已交给操作系统时不能回退数据库或提前归还资源，即使调用随后抛异常。
                self._unstarted = None
            raise
        self._unstarted = None

    def _return_unstarted(self, work: ExecutionWork) -> None:
        """本实例唯一的未启动领取才能退回；数据库失败仍归还未使用名额，并向主循环传播失败。"""
        running = self.running.get(work.record.job_id)
        if (
            self._unstarted is not work
            or (running is not None and running.thread.ident is not None)
            or work.claim is None
        ):
            raise DefectError()
        if not any(claim is work.claim for claim in self.resources.pool.claims()):
            raise DefectError()
        try:
            with session_scope_with_lock_timeout(
                self.dependencies.engine, busy_timeout_ms=policy.PROGRESS_LOCK_TIMEOUT_MS
            ) as session:
                return_unstarted_job(
                    session, work.record, mode=work.mode, now=self.dependencies.clock.now()
                )
                # 主循环逐次领取后立即启动或退回，不会在此间领取另一个作业。
                # 与领取字段同一事务恢复旧版本；已经启动的线程绝不进入此分支。
                if self.scheduler is None:
                    raise DefectError()
                row = session.get(JobRow, work.record.job_id)
                if row is None:
                    raise DefectError()
                row.platform_version = self.scheduler.previous_version
                session.flush()
        except BaseException as error:
            error.add_note(f"未启动领取退回失败 job_id={work.record.job_id}")
            raise
        finally:
            self._unstarted = None
            self.resources.pool.release(work.claim)

    def _execute(self, work: ExecutionWork, signals: ExecutionSignals) -> None:
        """执行边界已报告持久化失败，线程只通知主循环，不重复ERROR。"""
        try:
            execute_job(work, self.dependencies, signals)
        except Exception:
            self.execution_failed.set()

    def _observe(self, running: _Running) -> None:
        """独立传播取消，执行线程结束后仍须确认输出线程已回收。"""
        number = running.work.record.job_id
        if not running.thread.is_alive():
            running.thread.join(timeout=0)
            if self.execution_failed.is_set() or self._monitor_alive(running.monitor):
                self.failed = True
            else:
                self.running.pop(number)
            return
        with session_scope(self.dependencies.engine, read_only=True) as session:
            record = find_job(session, number)
        if record.state is JobState.CANCELLING:
            running.signals.cancelled.set()
            self._cancel_stall(running)

    def _cancel_stall(self, running: _Running) -> None:
        """每个作业独立计时且只警告一次，不把另一线程的取消时间混入。"""
        now = self.clock.read()
        if running.cancel_seen is None:
            running.cancel_seen = now
        elapsed = now - running.cancel_seen
        if running.cancel_warned or elapsed <= policy.CANCEL_STALL_WARNING_S:
            return
        running.cancel_warned = True
        number = running.work.record.job_id
        logger.warning("作业 job_id=%s 未响应取消 elapsed_s=%.3f，保持正在取消", number, elapsed)
        monitor = running.monitor
        if not monitor.lock.acquire(timeout=policy.OUTPUT_JOIN_TIMEOUT_S):
            return
        try:
            reporter = monitor.reporter
        finally:
            monitor.lock.release()
        if reporter is not None:
            try:
                progress = reporter.snapshot().progress
                reporter.diagnostic(
                    Diagnostic(
                        level=DiagnosticLevel.WARNING,
                        category=DiagnosticCategory.CONFLICT,
                        stage="未知阶段" if progress is None else progress.stage_name,
                        source="平台",
                        objects=(DiagnosticObject(key="job_id", value=str(number)),),
                        rule="执行函数须及时响应取消",
                        actual=f"已等待{elapsed:.3f}秒仍未响应取消",
                        expected="到达检查点后退出",
                        consequence="该作业保持正在取消并继续占用本类型名额",
                        next_step="检查执行函数检查点或重启worker",
                    )
                )
            except Exception:
                logger.warning("作业 job_id=%s 的取消诊断未完整写入，继续等待执行线程", number)

    def _monitor_alive(self, monitor: ExecutionMonitor) -> tuple[Thread, ...]:
        """只在短锁内复制存活线程，不在监视锁内join。"""
        if not monitor.lock.acquire(timeout=policy.OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            return tuple(thread for thread in monitor.threads if thread.is_alive())
        finally:
            monitor.lock.release()

    def _alive(self) -> tuple[Thread, ...]:
        """枚举本实例所有作业登记的存活线程，不扫描调用方无关线程。"""
        return tuple(
            thread
            for running in self.running.values()
            for thread in self._monitor_alive(running.monitor)
        )

    def _shutdown(self) -> WorkerLoopResult:
        """全部执行/读线程共用截止，坏注入时钟不能延长真实收尾上限。"""
        self.stop.set()
        real_deadline = time.monotonic() + policy.WORKER_STOP_TIMEOUT_S
        try:
            deadline: float | None = self.clock.read() + policy.WORKER_STOP_TIMEOUT_S
        except DefectError:
            self.failed = True
            deadline = None
        alive = self._alive()
        while alive:
            remaining = max(0.0, real_deadline - time.monotonic())
            if deadline is not None:
                try:
                    remaining = min(remaining, max(0.0, deadline - self.clock.read()))
                except DefectError:
                    self.failed = True
                    deadline = None
            if remaining <= 0:
                break
            alive[0].join(timeout=remaining)
            alive = self._alive()
        if alive:
            logger.error("worker停止超出预算，仍有daemon线程存活，实例锁保留到进程退出")
        failed = self.failed or self.execution_failed.is_set() or bool(alive)
        return WorkerLoopResult(
            policy.WORKER_EXIT_FAILURE if failed else policy.WORKER_EXIT_OK, alive
        )
