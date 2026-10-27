"""执行线程的进度、诊断与协作停止（08）；内存最新值和数据库节流明确分离。

使用 threading.Event/Lock 和注入 monotonic；不手写定时线程，不持有跨调用 Session。
数据库入场 BUSY/LOCKED 可跳过，事务已进入后的故障不能吞掉；执行器负责最后一次强制落库。
"""

from __future__ import annotations

import math
from _thread import LockType
from collections.abc import Callable, Generator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from threading import Event, Lock, Thread, get_ident
from types import TracebackType
from typing import cast

from pydantic import ValidationError
from sqlalchemy import Engine

from rdp.infra.db.connection import session_scope_with_lock_timeout
from rdp.infra.diagnostics import (
    ConflictError,
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    ExternalError,
    InputError,
)
from rdp.jobs import _diagnostics, _storage, _views
from rdp.jobs.errors import JobCancelledError, WorkerStoppingError
from rdp.jobs.logs import JobLog
from rdp.jobs.policy import (
    COUNT_MAX_INTERVAL_MS,
    JOB_ARTIFACT_LIMIT,
    JOB_ARTIFACT_MAX_CHARS,
    OUTPUT_JOIN_TIMEOUT_S,
    PROCESS_POLL_INTERVAL_S,
    PROGRESS_INTERVAL_S,
    PROGRESS_LOCK_TIMEOUT_MS,
    WORKER_OWNED_THREAD_LIMIT,
)
from rdp.jobs.records import save_progress
from rdp.jobs.resources import save_resource_display
from rdp.jobs.scheduling_types import ResourceDisplay
from rdp.jobs.types import ExecutionSnapshot, JobClock, JobProgress, JobRecord, JobState, WaitReason


@dataclass
class ExecutionMonitor:
    """主循环与执行器共享的有界生命周期记录，不靠线程名字猜资源归属。

    Attributes:
        threads: 本作业框架创建的线程列表，最多WORKER_OWNED_THREAD_LIMIT；启动前登记，全部daemon；
            只有join确认结束才移除，不在异常路径丢掉仍存活的读线程。
        reporter: 执行器创建后发布的ProgressReporter；发布前None，主循环用它报告取消超时诊断。
        lock: 所有字段读写共同持有的threading.Lock；等待最多OUTPUT_JOIN_TIMEOUT_S，不在锁内join或做I/O。
    """

    threads: list[Thread]
    reporter: ProgressReporter | None
    lock: LockType


@dataclass(frozen=True)
class ExecutionSignals:
    """区分人为取消与 worker 退出，两者不能互相冒充。

    Attributes:
        cancelled: 主循环观察数据库 cancelling 后置位；执行函数只读。
        stopping: 入口停止信号，worker 退出时置位；保留 running 供下个实例恢复。
        monitor: 本作业共享生命周期记录；仅框架写，执行函数不直接修改。
    """

    cancelled: Event
    stopping: Event
    monitor: ExecutionMonitor


class ProgressReporter:
    """每个执行上下文一个上报对象；执行线程写，主循环和输出线程可读取停止信号。"""

    def __init__(
        self,
        engine: Engine,
        record: JobRecord,
        log: JobLog,
        clock: JobClock,
        signals: ExecutionSignals,
    ) -> None:
        """建立内存最新进度和节流基线。

        Args:
            engine: 受管数据库引擎，不在实例中保存 Session。
            record: 本次执行前记录；续跑用最后持久化进度作累计基线，首报也不得低于它；
                同一阶段done不得倒退，阶段前进可清done但累计total_items/failed_items/warning_count不能倒退。
                执行函数自行累加上次值，不把增量当累计值；重跑已经清零，可重新从第一阶段开始。
            log: 本作业的线程安全追加日志，不接管关闭。
            clock: 注入 UTC 墙钟与有限单调秒时钟；非法值归 DefectError。
            signals: 分离的取消和停止 Event，不给隐式默认值。

        Returns:
            无；保存该实例的节流状态和已保存运行片段，不共享其他作业的状态。

        Raises:
            DefectError: 非运行中记录、依赖不合法或时钟回调非法。

        Side Effects:
            只建立内存快照和锁，不写数据库、文件或启动线程。

        Time Semantics:
            从构造时 monotonic 开始本片段计时；不把 started_at 与单调时钟相减。
        """
        if record.state is not JobState.RUNNING or not engine.get_execution_options().get(
            "rdp_managed"
        ):
            raise DefectError()
        self._engine, self._record, self._log = engine, record, log
        self._clock, self._signals = clock, signals
        self._lock = Lock()
        self._last_read: float | None = None
        self._started = self._monotonic()
        _storage.moment(clock.now())
        self._last_attempt: float | None = None
        self._revision = 0
        self._saved_revision = 0
        self._pending_resource: ResourceDisplay | None = None
        self._defer_owner: int | None = None
        self._deferred_timer = Event()
        self._progress = record.progress
        self._diagnostics = {(group.source, group.rule): group for group in record.diagnostics}
        self._artifacts = list(record.artifacts)
        self._tool_exit_code = record.tool_exit_code
        _views.snapshot_data(self.snapshot())

    @property
    def job_id(self) -> int:
        """本作业正编号（1至2^63-1），供框架补诊断身份，只读且不访问数据库。"""
        return self._record.job_id

    @property
    def clock(self) -> JobClock:
        """本作业注入的UTC墙钟和单调秒时钟，只读，框架不另取隐式系统时钟。"""
        return self._clock

    def report(self, progress: JobProgress) -> None:
        """保留最新完整进度，并按一秒预算尝试短事务写入。

        Args:
            progress: 校验后的进度；只能在真实完成事件之后增加 done/条目数。

        Returns:
            无；即使未到落库时刻或拿不到短锁，snapshot 始终返回此次最新值。

        Raises:
            DefectError: 进度非法、同阶段 done/累计计数倒退、阶段序号倒退，或注入时钟错误。
            InputError: 数据库损坏。
            ConflictError: 已进入事务后的竞争/约束错误，不能视为短锁跳过。
            ExternalError: 已进入事务的数据库故障或阶段日志写入失败。

        Side Effects:
            先更新内存；阶段变更追加日志。距上次尝试至少 PROGRESS_INTERVAL_S 才申请
            PROGRESS_LOCK_TIMEOUT_MS 短锁并 save_progress；BEGIN BUSY/LOCKED 跳过，保留最新值，
            下一秒才再试，不高频重试。report、check_cancelled、wait和外部进程轮询共用flush_due，
            不各自维护节流器；成功保存所取快照后才清对应脏标记，期间的新值仍待补写。
            非入场忙的错误传播给执行器，事务回滚。

        Time Semantics:
            节流只用 monotonic，墙钟回拨不影响频率；每次数据库更新时间用 UTC。
            一秒多次report至多一次周期写入；没有后续report时也须按next_flush_deadline补写，
            无锁竞争的调度目标为1秒，获锁最多另加100毫秒及本地I/O/系统调度耗时；
            连续跳过n次短锁则另加n*PROGRESS_INTERVAL_S，持续锁忙没有有限持久化延迟保证。
            最终写入由执行器正常锁事务独立保证。
        """
        try:
            checked = JobProgress.model_validate(progress.model_dump())
        except (AttributeError, ValidationError):
            raise DefectError() from None
        with self._guard():
            previous = self._progress
            _validate_advance(previous, checked)
            self._progress = checked
            self._revision += 1
        if previous is None or (previous.stage_index, previous.stage_name) != (
            checked.stage_index,
            checked.stage_name,
        ):
            self._log.write_line(
                f"阶段 {checked.stage_index}/{checked.stage_count} · {checked.stage_name}",
                now=self._clock.now(),
            )
        self.flush_due()

    def diagnostic(self, diagnostic: Diagnostic) -> None:
        """记录诊断原文并保留有界样例和完整总数。

        Args:
            diagnostic: 统一五段诊断，包含作业/阶段身份，不含秘密或整份载荷。

        Returns:
            无；各来源/规则的总数完整，样例不超过 DIAGNOSTIC_SAMPLE_LIMIT。

        Raises:
            DefectError: 非法诊断或来源身份不一致。
            ExternalError: 完整作业日志写入失败。

        Side Effects:
            每条写日志并刷新，内存只保留有界分组；超过规则组上限合并至明确标记的溢出组。
            不根据诊断级别自动增加 failed_items/warning_count；执行函数上报真实口径计数。

        Time Semantics:
            样例按到达顺序，不按回拨墙钟重新排序；日志锁有 OUTPUT_JOIN_TIMEOUT_S 预算。
        """
        try:
            checked = Diagnostic.model_validate(diagnostic.model_dump())
        except (AttributeError, ValidationError):
            raise DefectError() from None
        if any(
            item.key == "job_id" and item.value != str(self._record.job_id)
            for item in checked.objects
        ):
            raise DefectError()
        self._retain_diagnostic(checked)
        self._log.write_diagnostic(checked, now=self._clock.now())

    def next_flush_deadline(self) -> float | None:
        """取得待保存进度的下次单调补写截止。

        Args:
            无。

        Returns:
            有脏快照时返回上次尝试起点加PROGRESS_INTERVAL_S的单调秒值；没有待写值为None。
            已过截止返回原截止，不顺延；首次脏值尚无尝试时立即到期。

        Raises:
            DefectError: 时钟或内部节流状态非法。

        Side Effects:
            无；只读有界内存状态，不取数据库锁。

        Time Semantics:
            wait和外部进程等待取此截止与信号检查截止的较早者；长计算执行函数同样须在此截止前
            到达检查点，不能仅依赖两次调用间隔不超过一秒而跨过已知补写截止。
        """
        with self._guard():
            now = self._monotonic()
            if self._revision == self._saved_revision:
                return None
            return now if self._last_attempt is None else self._last_attempt + PROGRESS_INTERVAL_S

    def flush_due(self) -> None:
        """把到期的脏快照补写一次，供报告、检查点和等待轮询共用。

        Args:
            无。

        Returns:
            无；未到期、无脏值或BEGIN短锁忙时不写，内存最新值始终保留。

        Raises:
            InputError: 数据库损坏。
            ConflictError: 已进入事务的竞争/提交失败，不当作短锁跳过。
            ExternalError: 快照持久化I/O失败。
            DefectError: 非法时钟、快照或跨线程生命周期错误。

        Side Effects:
            到期用PROGRESS_LOCK_TIMEOUT_MS短锁保存最新快照，BEGIN BUSY/LOCKED仅跳过本次；
            report和各等待路径共用同一尝试时刻和脏标记，不能在一秒内叠加写入或无限重试。
            同时补写 set_resource_display 的最新脏副本，清持锁标记不能因没有新进度而永远遗漏。

        Time Semantics:
            只用monotonic节流，每次尝试起点间至少PROGRESS_INTERVAL_S；无后续report也会在
            检查点、wait或外部进程轮询到截止时补写。延迟为1秒目标加获锁/I/O/调度，以及连续跳过次数乘1秒。
        """
        with self._guard():
            now = self._monotonic()
            if self._revision == self._saved_revision or (
                self._last_attempt is not None and now < self._last_attempt + PROGRESS_INTERVAL_S
            ):
                return
            self._last_attempt = now
            revision = self._revision
            snapshot = self._snapshot(now)
            resource = self._pending_resource
        entered = False
        try:
            with session_scope_with_lock_timeout(
                self._engine, busy_timeout_ms=PROGRESS_LOCK_TIMEOUT_MS
            ) as session:
                entered = True
                save_progress(
                    session, self._record.job_id, snapshot, now=_storage.moment(self._clock.now())
                )
                if resource is not None:
                    save_resource_display(session, self._record.job_id, resource)
        except ConflictError as error:
            if not entered and _storage.entry_busy(error):
                return
            raise
        with self._guard():
            # 保存期间其他线程新增的诊断/产物仍是脏值，不能清掉最新版本。
            self._saved_revision = revision
            if self._pending_resource is resource:
                self._pending_resource = None

    def set_resource_display(self, display: ResourceDisplay) -> None:
        """记录本作业的最新等待/持锁副本并尝试短锁落库。

        Args:
            display: 合法 ResourceDisplay；执行线程只能设置写锁等待或持锁，GPU 排队由主循环发布。

        Returns:
            无；短锁忙时内存保留最新值，后续检查点补写，不丢掉释放锁后的清空。

        Raises:
            InputError: 资源存储读取或更新遇数据库损坏。
            ConflictError: 已进入事务后的冲突，不能当作可跳过的 BEGIN 忙。
            ExternalError: 资源副本 I/O 失败。
            DefectError: 状态组合错误或非本作业生命周期调用。

        Side Effects:
            直接用已有 engine 开短事务调用 save_resource_display；只写本作业的导航锁等待/持锁，
            queued 的 GPU 等待唯一由主循环写。BEGIN 忙时只保留本作业最新值及版本，内存有界。
            flush_due 统一补写，过期版本不能覆盖新版本，终态最后由执行器普通事务强制清空。

        Time Semantics:
            状态改变可立即一次短锁尝试，随后每 PROGRESS_INTERVAL_S 再试，使用同一单调节流器；
            不等待数据库写成功才允许释放导航锁。
        """
        if (
            not isinstance(cast(object, display), ResourceDisplay)
            or type(display.holds_navigation_lock) is not bool
        ):
            raise DefectError()
        if (
            display.wait_reason is not None
            and display.wait_reason is not WaitReason.NAVIGATION_LOCK
        ):
            raise DefectError()
        if display.holds_navigation_lock and display.wait_reason is not None:
            raise DefectError()
        with self._guard():
            self._pending_resource = display
            self._revision += 1
        self.flush_due()

    def defer_cancellation(self) -> AbstractContextManager[None]:
        """给导航写锁的持锁段提供协作取消屏蔽范围。

        Args:
            无。

        Returns:
            仅限当前执行线程使用的一次性上下文管理器；退出不主动检查取消或清除信号。

        Raises:
            DefectError: 嵌套屏蔽、跨线程进入/退出或重复使用同一上下文。

        Side Effects:
            进入后 check_cancelled/wait 不抛 JobCancelledError 或 WorkerStoppingError，
            仍补写进度和资源，普通 I/O/缺陷照常传播；finally 恢复屏蔽状态，不掩盖写回调异常。

        Time Semantics:
            只在获得导航锁并做最后一次取消检查后进入；verify/write 完成并放锁后退出，
            后续下一次 check_cancelled 才响应已保存的信号，不能在持锁时强制结束线程。
        """
        return _CancellationDeferral(self._enter_deferral, self._exit_deferral)

    def _enter_deferral(self) -> None:
        """同一上报对象不能被另一个保护段占用；持有者只记录当前执行线程。"""
        with self._guard():
            if self._defer_owner is not None:
                raise DefectError()
            self._defer_owner = get_ident()

    def _exit_deferral(self) -> None:
        """只有进入保护段的执行线程可以恢复取消检查。"""
        with self._guard():
            if self._defer_owner != get_ident():
                raise DefectError()
            self._defer_owner = None

    def check_cancelled(self) -> None:
        """补写到期进度并检查取消或停止，阻止继续处理新条目。

        Args:
            无。

        Returns:
            无；没有停止信号，或当前处于导航写锁的 defer_cancellation 范围时返回。

        Raises:
            JobCancelledError: cancelled已置位且不在屏蔽范围，优先于stopping和补写故障；补写失败保留给最终收尾诊断。
            WorkerStoppingError: 仅stopping已置位且不在屏蔽范围，执行器不落终态。
            InputError: 无停止信号时补写遇数据库损坏。
            ConflictError: 无停止信号时补写已进入事务后失败。
            ExternalError: 无停止信号时补写I/O失败。
            DefectError: 无停止信号时快照、时钟或生命周期非法。

        Side Effects:
            有脏值且到期时调用flush_due，最多一次短锁尝试；不自行写作业状态或清理产物。
            先观察信号，执行有界补写，再核验信号，不能因持续锁忙让取消一直不返回。

        Time Semantics:
            阶段前后、每步完成后调用；脏值存在时必须在next_flush_deadline前进入检查点，
            其他计算段检查间隔至多JOB_CHECKPOINT_MAX_S。一次短锁可另占100毫秒，不无限等待补写成功。
        """
        with self._guard():
            deferred = self._defer_owner == get_ident()
        cancelled, stopping = self._signals.cancelled.is_set(), self._signals.stopping.is_set()
        try:
            self.flush_due()
        except (InputError, ConflictError, ExternalError, DefectError) as error:
            if deferred or not (
                cancelled
                or stopping
                or self._signals.cancelled.is_set()
                or self._signals.stopping.is_set()
            ):
                raise
            # 不把停止控制信号换成存储故障；诊断留在快照供最终收尾保存。
            for diagnostic in error.diagnostics:
                self._retain_diagnostic(diagnostic)
        if not deferred and (cancelled or self._signals.cancelled.is_set()):
            raise JobCancelledError(
                (
                    _storage.diagnostic(
                        self._record.job_id, "作业收到取消请求", DiagnosticCategory.CONFLICT
                    ),
                )
            )
        if not deferred and (stopping or self._signals.stopping.is_set()):
            raise WorkerStoppingError(
                (
                    _storage.diagnostic(
                        self._record.job_id, "worker正在停止", DiagnosticCategory.CONFLICT
                    ),
                )
            )

    def wait(self, interval_s: float) -> None:
        """等待可由取消打断、并持续补写脏进度的单调时长。

        Args:
            interval_s: 有限非负秒数，至多COUNT_MAX_INTERVAL_MS/1000；零值仍检查信号及到期补写。

        Returns:
            无；完整经过interval_s且无信号时返回，期间无需再次report才能持久化最新值。

        Raises:
            JobCancelledError: 等待前或期间取消，优先于停止和补写失败，不等满间隔。
            WorkerStoppingError: 入口停止且无取消请求。
            InputError: 无停止信号时补写遇数据库损坏。
            ConflictError: 无停止信号时补写入场后的冲突。
            ExternalError: 无停止信号时补写I/O失败。
            DefectError: 时长越界、时钟非法或快照缺陷。

        Side Effects:
            Event小段等待不持数据库锁；每次醒来检查信号并调用flush_due，不因没有新report漏掉最新值。
            defer_cancellation 期间不用已置位的取消 Event 作等待对象，改用有界计时等待，避免忙等；
            仍遵守相同单调截止和补写周期，不因屏蔽信号而跳过整个 interval_s。
            仅到期且有脏数据才申请一次短锁，拿不到保留并在下一秒再试。

        Time Semantics:
            唤醒截止取等待结束、信号轮询和next_flush_deadline中最早者，不把补写推迟到长等待结束。
            无锁竞争约1秒内补写，另计至多100毫秒获锁及I/O/调度；每次连续短锁跳过另加1秒。
            信号响应至多PROCESS_POLL_INTERVAL_S加已在途的短锁预算，墙钟回拨不影响截止。
        """
        if (
            type(interval_s) not in {int, float}
            or not math.isfinite(interval_s)
            or not 0 <= interval_s <= COUNT_MAX_INTERVAL_MS / 1000
        ):
            raise DefectError()
        with self._guard():
            deadline = self._monotonic() + interval_s
        while True:
            self.check_cancelled()
            with self._guard():
                now = self._monotonic()
            if now >= deadline:
                return
            flush = self.next_flush_deadline()
            wake = min(
                deadline, now + PROCESS_POLL_INTERVAL_S, flush if flush is not None else deadline
            )
            with self._guard():
                deferred = self._defer_owner == get_ident()
            # 已置位取消Event会立即返回；保护段改等永不置位的计时Event，避免忙等。
            waiter = self._deferred_timer if deferred else self._signals.cancelled
            waiter.wait(max(0, wake - now))

    def track_output_thread(self, thread: Thread) -> None:
        """在启动前登记一个daemon输出线程，供停止边界核验存活资源。

        Args:
            thread: 尚未start的输出读取Thread，daemon必须True；归当前作业，不接受无关线程。

        Returns:
            无；线程加入signals.monitor，主循环即使执行线程已经结束也能发现它。

        Raises:
            DefectError: 非daemon、已启动、重复登记、超过WORKER_OWNED_THREAD_LIMIT或监视锁超时。

        Side Effects:
            在monitor.lock下更新有界线程列表；只移除已join确认结束的旧线程，不启动线程、不做I/O。

        Time Semantics:
            必须先登记再start；监视锁最多OUTPUT_JOIN_TIMEOUT_S，禁止持锁join，失败不启动输入线程。
        """
        monitor = self._signals.monitor
        if not thread.daemon or thread.ident is not None:
            raise DefectError()
        if not monitor.lock.acquire(timeout=OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            if thread in monitor.threads:
                raise DefectError()
            finished = [
                item for item in monitor.threads if item.ident is not None and not item.is_alive()
            ]
        finally:
            monitor.lock.release()
        # join只能在锁外；已结束线程用零等待确认回收，避免主循环等待同一锁。
        for item in finished:
            item.join(timeout=0)
        if not monitor.lock.acquire(timeout=OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            monitor.threads[:] = [item for item in monitor.threads if item not in finished]
            if thread in monitor.threads or len(monitor.threads) >= WORKER_OWNED_THREAD_LIMIT:
                raise DefectError()
            monitor.threads.append(thread)
        finally:
            monitor.lock.release()

    def artifact(self, location: str) -> None:
        """保留一个产物位置供最后摘要使用，不检查或修改产物。

        Args:
            location: 非空无秘密位置文本，至多 JOB_ARTIFACT_MAX_CHARS；总项数不超过 JOB_ARTIFACT_LIMIT。

        Returns:
            无；按首次报告顺序去重保存。

        Raises:
            DefectError: 空文本、长度或数量超限，不静默丢产物记录。

        Side Effects:
            仅更新内存；不访问任何导航层或存储根。

        Time Semantics:
            同步有界插入，无时钟和等待。
        """
        if (
            not isinstance(cast(object, location), str)
            or not location.strip()
            or len(location) > JOB_ARTIFACT_MAX_CHARS
        ):
            raise DefectError()
        with self._guard():
            if location in self._artifacts:
                return
            if len(self._artifacts) >= JOB_ARTIFACT_LIMIT:
                raise DefectError()
            self._artifacts.append(location)
            self._revision += 1

    def tool_exit(self, returncode: int) -> None:
        """保存最近一次外部进程的真实退出码。

        Args:
            returncode: subprocess 的严格整数返回值，负数为终止信号。

        Returns:
            无；snapshot 返回该值，无进程时一直为 None。

        Raises:
            DefectError: bool 或非整数，不将未知退出伪造成零。

        Side Effects:
            只更新内存，不计算结果或转换状态。

        Time Semantics:
            进程 wait/reap 完成后调用，不读取墙钟。
        """
        if type(returncode) is not int:
            raise DefectError()
        with self._guard():
            self._tool_exit_code = returncode
            self._revision += 1

    def snapshot(self) -> ExecutionSnapshot:
        """冻结最新值供最终普通事务及中断诊断使用。

        Args:
            无。

        Returns:
            原子快照，含未落库的最新进度、完整聚合计数、产物、退出码及单调耗时。

        Raises:
            DefectError: 单调时钟非法或内部计数不满足约束。

        Side Effects:
            无；不清空内存，不持数据库会话。

        Time Semantics:
            本次 elapsed_s 用 monotonic 计算；内存锁预算 OUTPUT_JOIN_TIMEOUT_S，超时归 DefectError。
        """
        with self._guard():
            return self._snapshot(self._monotonic())

    @contextmanager
    def _guard(self) -> Generator[None]:
        """所有内存字段共享有限写锁，不在锁内做数据库或文件I/O。"""
        if not self._lock.acquire(timeout=OUTPUT_JOIN_TIMEOUT_S):
            raise DefectError()
        try:
            yield
        finally:
            self._lock.release()

    def _monotonic(self) -> float:
        """验证注入时钟有限且不回退；调用者持内存锁，构造阶段没有并发。"""
        value = self._clock.monotonic()
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or (self._last_read is not None and value < self._last_read)
        ):
            raise DefectError()
        self._last_read = value
        return value

    def _snapshot(self, now: float) -> ExecutionSnapshot:
        """一次锁内冻结全部最新字段；保存过的片段只加一次，不把离线时间计入。"""
        snapshot = ExecutionSnapshot(
            self._progress,
            tuple(self._diagnostics.values()),
            tuple(self._artifacts),
            self._tool_exit_code,
            self._record.elapsed_s + now - self._started,
        )
        checked, _ = _views.snapshot_data(snapshot)
        return checked

    def _retain_diagnostic(self, diagnostic: Diagnostic) -> None:
        """只聚合有界样例，原始来源/规则不为溢出分组而改写。"""
        with self._guard():
            groups = _diagnostics.append(tuple(self._diagnostics.values()), diagnostic)
            self._diagnostics = {(group.source, group.rule): group for group in groups}
            self._revision += 1


def _validate_advance(previous: JobProgress | None, current: JobProgress) -> None:
    """续跑基线和普通上报共用累计校验；只有阶段向前时done可以从零开始。"""
    if previous is None:
        return
    if current.stage_index < previous.stage_index:
        raise DefectError()
    if current.stage_index == previous.stage_index and current.done < previous.done:
        raise DefectError()
    if any(
        new < old
        for new, old in (
            (current.total_items, previous.total_items),
            (current.failed_items, previous.failed_items),
            (current.warning_count, previous.warning_count),
        )
    ):
        raise DefectError()


class _CancellationDeferral(AbstractContextManager[None]):
    """一次性、限创建线程使用的取消屏蔽范围；退出不主动抛取消。"""

    def __init__(self, enter: Callable[[], None], leave: Callable[[], None]) -> None:
        """保存限当前上报对象的进入/退出能力，不跨类访问其私有字段。"""
        self.enter, self.leave = enter, leave
        self.owner = get_ident()
        self.used = False
        self.active = False

    def __enter__(self) -> None:
        """只允许一次成功进入，拒绝嵌套或把管理器交到另一线程。"""
        if self.used or get_ident() != self.owner:
            raise DefectError()
        self.enter()
        self.used = self.active = True

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """恢复信号检查，不清除Event，不掩盖回调原异常。"""
        if not self.active or get_ident() != self.owner:
            raise DefectError()
        self.leave()
        self.active = False
        return False
