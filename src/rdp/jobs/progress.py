"""执行线程的进度、诊断与协作停止（08）；内存最新值和数据库节流明确分离。

使用 threading.Event/Lock 和注入 monotonic；不手写定时线程，不持有跨调用 Session。
数据库入场 BUSY/LOCKED 可跳过，事务已进入后的故障不能吞掉；执行器负责最后一次强制落库。
"""

from __future__ import annotations

from _thread import LockType
from dataclasses import dataclass
from threading import Event, Thread

from sqlalchemy import Engine

from rdp.infra.diagnostics import Diagnostic
from rdp.jobs.logs import JobLog
from rdp.jobs.types import ExecutionSnapshot, JobClock, JobProgress, JobRecord


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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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

        Time Semantics:
            只用monotonic节流，每次尝试起点间至少PROGRESS_INTERVAL_S；无后续report也会在
            检查点、wait或外部进程轮询到截止时补写。延迟为1秒目标加获锁/I/O/调度，以及连续跳过次数乘1秒。
        """
        raise NotImplementedError

    def check_cancelled(self) -> None:
        """补写到期进度并检查取消或停止，阻止继续处理新条目。

        Args:
            无。

        Returns:
            无；补写检查结束且没有停止信号时返回。

        Raises:
            JobCancelledError: cancelled已置位，优先于stopping和补写故障；补写失败保留给最终收尾诊断。
            WorkerStoppingError: 仅stopping已置位，执行器不落终态。
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
        raise NotImplementedError

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
            仅到期且有脏数据才申请一次短锁，拿不到保留并在下一秒再试。

        Time Semantics:
            唤醒截止取等待结束、信号轮询和next_flush_deadline中最早者，不把补写推迟到长等待结束。
            无锁竞争约1秒内补写，另计至多100毫秒获锁及I/O/调度；每次连续短锁跳过另加1秒。
            信号响应至多PROCESS_POLL_INTERVAL_S加已在途的短锁预算，墙钟回拨不影响截止。
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError
