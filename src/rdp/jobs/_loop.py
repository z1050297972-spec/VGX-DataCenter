"""worker 循环内部边界；主线程只做短事务，每作业独立 monitor，所有线程共用停止预算。"""

# 待实现：把单 thread/signals/monitor 槽替换为按 job_id 的有界集合，统一完成恢复准备后按每类队首调用 Scheduler，逐轮重判 GPU 等待并执行定时检查。

import logging
import time
from contextvars import copy_context
from dataclasses import replace
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
from rdp.jobs.records import claim_job, find_job, next_queued_job, save_heartbeat
from rdp.jobs.scheduling_types import ResourceClaim
from rdp.jobs.types import ExecutionMode, JobState, WorkerHeartbeat
from rdp.jobs.worker import WorkerLoopResult

logger = logging.getLogger(__name__)


class Loop:
    """一次worker实例状态；停止或执行持久化失败后不再写心跳或领取。"""

    def __init__(
        self, dependencies: ExecutorDependencies, stop: Event, heartbeat: WorkerHeartbeat
    ) -> None:
        """保存本实例依赖、恢复游标和线程监视状态，初始时钟非法在启动前拒绝。"""
        self.dependencies, self.stop, self.heartbeat = dependencies, stop, heartbeat
        self.clock = ClockReader(dependencies.clock)
        self.next_heartbeat = self.clock.read()
        self.cursor = 0
        self.recovery_done = False
        self.monitor: ExecutionMonitor | None = None
        self.signals: ExecutionSignals | None = None
        self.thread: Thread | None = None
        self.job_id: int | None = None
        self.failed = False
        self.execution_failed = Event()
        self.cancel_seen: float | None = None
        self.cancel_warned = False

    def run(self) -> WorkerLoopResult:
        """循环结束共用一个停止截止；运行中的基础设施故障转换失败结果。"""
        try:
            while not self.stop.is_set():
                if self.execution_failed.is_set():
                    self.failed = True
                    break
                self._heartbeat()
                if self.thread is not None:
                    self._observe()
                else:
                    work = self._next()
                    if work is not None:
                        self._start(work)
                if self.failed:
                    break
                self.stop.wait(policy.WORKER_POLL_INTERVAL_S)
        except Exception:
            self.failed = True
            logger.error("worker主循环失败，停止领取及心跳", exc_info=True)
        return self._shutdown()

    def _heartbeat(self) -> None:
        """入场短锁忙仅警告一次；入场后失败不隐藏成正常在线。"""
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

    def _next(self) -> ExecutionWork | None:
        """恢复扫描每次只取一个编号；失败行保留running也不会再次命中。"""
        if not self.recovery_done:
            with session_scope(self.dependencies.engine, read_only=True) as session:
                job_id = session.scalar(
                    select(JobRow.job_id)
                    .where(
                        JobRow.job_id > self.cursor,
                        JobRow.state.in_((JobState.RUNNING.value, JobState.CANCELLING.value)),
                    )
                    .order_by(JobRow.job_id)
                    .limit(1)
                )
            if job_id is not None:
                self.cursor = job_id
                return recover_job(job_id, self.dependencies)
            self.recovery_done = True
        with session_scope(self.dependencies.engine, read_only=True) as session:
            candidate = next_queued_job(session)
        if candidate is None:
            return None
        try:
            with session_scope(self.dependencies.engine) as session:
                record = claim_job(
                    session,
                    candidate.job_id,
                    now=self.dependencies.clock.now(),
                    paths=self.dependencies.paths,
                    gpu_index=None,
                )
        except ConflictError:
            # Web可能先提交排队取消；不把正常的条件更新落败当作执行失败。
            return None
        return ExecutionWork(
            record,
            ExecutionMode.FRESH,
            None,
            claim=ResourceClaim(record.job_id, record.type_name, record.gpu_index),
        )

    def _start(self, work: ExecutionWork) -> None:
        """登记daemon执行线程后才start，显式复制调用方contextvars。"""
        self.monitor = ExecutionMonitor([], None, Lock())
        self.signals = ExecutionSignals(Event(), self.stop, self.monitor)
        self.job_id = work.record.job_id
        self.cancel_seen = None
        self.cancel_warned = False
        context = copy_context()
        self.thread = Thread(
            target=context.run, args=(self._execute, work, self.signals), daemon=True
        )
        self.monitor.threads.append(self.thread)
        self.thread.start()

    def _execute(self, work: ExecutionWork, signals: ExecutionSignals) -> None:
        """执行器已记录持久化失败，本线程只通知主循环，不重复ERROR。"""
        try:
            execute_job(work, self.dependencies, signals)
        except Exception:
            self.execution_failed.set()

    def _observe(self) -> None:
        """执行函数未返回时仍查取消，返回后先确认全部输出资源结束才能领取下一条。"""
        if not (self.thread is not None and self.signals is not None and self.job_id is not None):
            raise DefectError()
        if not self.thread.is_alive():
            self.thread.join(timeout=0)
            if self.execution_failed.is_set() or self._alive():
                self.failed = True
            else:
                self.thread = None
            return
        with session_scope(self.dependencies.engine, read_only=True) as session:
            record = find_job(session, self.job_id)
        if record.state is JobState.CANCELLING:
            self.signals.cancelled.set()
            self._cancel_stall()

    def _cancel_stall(self) -> None:
        """首次观察取消计单调时长；先置一次标记，日志故障也不反复打扰。"""
        now = self.clock.read()
        if self.cancel_seen is None:
            self.cancel_seen = now
        elapsed = now - self.cancel_seen
        if self.cancel_warned or elapsed <= policy.CANCEL_STALL_WARNING_S:
            return
        self.cancel_warned = True
        logger.warning(
            "作业 job_id=%s 未响应取消，已等 %.3f 秒，保持正在取消", self.job_id, elapsed
        )
        monitor = self.monitor
        if monitor is None or not monitor.lock.acquire(timeout=policy.OUTPUT_JOIN_TIMEOUT_S):
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
                        objects=(DiagnosticObject(key="job_id", value=str(self.job_id)),),
                        rule="执行函数须及时响应取消",
                        actual=f"已等待{elapsed:.3f}秒仍未响应取消",
                        expected="到达检查点后退出",
                        consequence="作业保持正在取消，暂不能领取下一作业",
                        next_step="检查执行函数检查点或重启worker",
                    )
                )
            except Exception:
                logger.warning("作业 job_id=%s 的取消诊断未完整写入，继续等待执行线程", self.job_id)

    def _alive(self) -> tuple[Thread, ...]:
        """monitor只在短锁内读列表，不在锁内join。"""
        if self.monitor is None:
            return ()
        if not self.monitor.lock.acquire(timeout=policy.OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            return tuple(thread for thread in self.monitor.threads if thread.is_alive())
        finally:
            self.monitor.lock.release()

    def _shutdown(self) -> WorkerLoopResult:
        """共享总预算回收全部登记线程；坏注入时钟不能让收尾也失败或无限等待。"""
        self.stop.set()
        real_deadline = time.monotonic() + policy.WORKER_STOP_TIMEOUT_S
        try:
            deadline: float | None = self.clock.read() + policy.WORKER_STOP_TIMEOUT_S
        except DefectError:
            self.failed = True
            deadline = None
        alive = self._alive()
        while alive:
            # 真实单调上限防止坏/停滞的注入时钟扩展等待；正常情况仍受注入截止约束。
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
