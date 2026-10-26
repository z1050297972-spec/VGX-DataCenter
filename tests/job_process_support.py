"""08真实子进程测试的隔离夹具契约；所有状态/日志/握手文件均位于pytest临时目录。"""

import gc
import json
import os
import signal
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from typing import cast

from accounts_support import AUDIT_CONTEXT, EXAMPLE_SECRET, model_row
from argon2 import PasswordHasher
from pydantic import BaseModel, ConfigDict

from rdp.accounts.security import PasswordCodec
from rdp.accounts.service import AccountService
from rdp.accounts.types import Credentials
from rdp.infra.actors import ActorRef
from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import migrate
from rdp.infra.logging import LoggingSettings
from rdp.infra.state import initialize_state, state_paths
from rdp.jobs import policy
from rdp.jobs.example import execute_count
from rdp.jobs.execution import ExecutionContext, ExecutionWork, ExecutorDependencies
from rdp.jobs.models import WorkerHeartbeatRow
from rdp.jobs.policy import WORKER_STOP_TIMEOUT_S
from rdp.jobs.processes import ToolCommand
from rdp.jobs.progress import ExecutionSignals
from rdp.jobs.records import NewJob, find_job, insert_job
from rdp.jobs.registry import JobDefinition, JobRegistry, production_registry
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobClock, JobProgress, JobRecord, JobState, RecoveryMode
from rdp.ops.worker import WorkerExit, run_worker

# 真实进程握手预算，单位秒；不以固定sleep猜测worker已经持锁或写完进度。
PROCESS_READY_TIMEOUT_S = 15.0
PROCESS_EXIT_TIMEOUT_S = 5.0
# 等入口返回的预算必须覆盖生产30秒收尾；额外5秒仅留给进程调度。
PROCESS_STOP_TIMEOUT_S = WORKER_STOP_TIMEOUT_S + PROCESS_EXIT_TIMEOUT_S
# 超时锁测试刻意在入口失败返回后继续保活，最多60秒，父进程授权退出或finally强制清理。
FAILED_WORKER_HOLD_S = 60.0
# SIGTERM宽限10秒，计时断言留出主循环一秒及机器调度余量，不接受立即KILL。
CANCEL_MIN_ELAPSED_S = 9.5
CANCEL_MAX_ELAPSED_S = 15.0


@dataclass(frozen=True)
class ProcessCase:
    """临时数据库里的测试账号、测试类型和可观测握手，不依赖真实账号或数据。"""

    root: Path
    job_id: int
    queued_job_id: int

    def wait_running(self, timeout_s: float) -> JobRecord:
        """有界等待worker持锁、已上报第3条且数据库确实保存第3条，返回数据库快照。

        执行函数第三次report后进入长reporter.wait；其到期补写确保无竞争时约1秒内落库，
        父进程以已提交数据库内容作为握手，不能把“report返回”当持久化完成。

        Returns:
            已持久化第3条进度的作业快照。
        """

        def ready() -> bool:
            record = _record(self.root, self.job_id)
            blocked_ready = (
                _configuration(self.root)["mode"] != "shutdown_timeout"
                or (self.root / "blocked-ready").exists()
            )
            return (
                record.state is JobState.RUNNING
                and record.progress is not None
                and record.progress.done == 3
                and blocked_ready
            )

        _wait(ready, timeout_s)
        return _record(self.root, self.job_id)

    def wait_terminal(self, timeout_s: float) -> JobRecord:
        """有界等待测试作业终态；超时附子进程日志，不把超时当通过。"""
        return _terminal(self.root, self.job_id, timeout_s)

    def wait_queued_terminal(self, timeout_s: float) -> JobRecord:
        """有界等待原恢复作业后面的新queued作业结束，再断言完整执行顺序。"""
        return _terminal(self.root, self.queued_job_id, timeout_s)

    def interruption(self) -> tuple[JobProgress | None, str]:
        """解析最后中断段的结构化进度和处理方式，与数据库独立逐字段比较。"""
        lines = _log(self.root, self.job_id).splitlines()
        data = json.loads(
            [line.split("interruption=", 1)[1] for line in lines if "interruption=" in line][-1]
        )
        return (
            None if data["progress"] is None else JobProgress.model_validate(data["progress"]),
            data["mode"],
        )

    def execution_modes(self) -> tuple[str, ...]:
        """读取测试执行函数写入的模式握手，fresh后应为resume/restart，interrupt没有第二次执行。"""
        return tuple(
            str(event["mode"]) for event in _events(self.root) if event["job_id"] == self.job_id
        )

    def resumed_progress(self) -> tuple[JobProgress | None, JobProgress | None]:
        """返回测试函数收到的previous_progress和本次起始进度，检查续跑保留与重跑清零。"""
        event = [event for event in _events(self.root) if event["job_id"] == self.job_id][-1]
        previous, initial = event["previous"], event["initial"]
        return (
            None if previous is None else JobProgress.model_validate(previous),
            None if initial is None else JobProgress.model_validate(initial),
        )

    def wait_claimed_before_log(self, timeout_s: float) -> JobRecord:
        """等待claim_gap夹具在领取提交后、打开日志前暂停；读库确认running和log_path均已提交。"""
        _wait(lambda: (self.root / "claim-gap").exists(), timeout_s)
        return _record(self.root, self.job_id)

    def log_section_order(self) -> tuple[str, ...]:
        """从真实日志的段落标记提取header/interruption/summary顺序；没有开头不能用中断段字段冒充。"""
        kinds = (
            ("作业开头", "header"),
            (" interruption=", "interruption"),
            (" summary=", "summary"),
        )
        return tuple(
            kind
            for line in _log(self.root, self.job_id).splitlines()
            for marker, kind in kinds
            if marker in line
        )

    def wait_tool_ready(self, timeout_s: float) -> None:
        """有界等待本工具的stdout前缀ready完整行已flush到作业日志，再允许取消或读取pid。

        ready只能在工具安装SIGTERM忽略处理器之后打印；超时失败，不能仅以作业running替代。
        """
        _wait(lambda: "│ready" in _log(self.root, self.job_id), timeout_s)

    def wait_worker_return(self, timeout_s: float) -> WorkerExit:
        """读取真实子进程夹具记录的run_worker返回结果；调用方保活，不能把进程退出当入口返回。"""
        path = self.root / f"returned-{_heartbeat(self.root).pid}.json"
        _wait(path.exists, timeout_s)
        return WorkerExit(**json.loads(path.read_text()))

    def allow_process_exit(self) -> None:
        """通知超时锁夹具结束失败返回后的保活，用原WorkerExit.code退出，不手动解锁。"""
        (self.root / f"exit-{_heartbeat(self.root).pid}").touch()

    def request_cancel(self) -> None:
        """以另一测试账号经JobService取消当前作业，不能直接UPDATE状态绕开状态机。"""
        engine = create_database_engine(self.root / "rdp.sqlite3")
        try:
            accounts = AccountService(
                engine, PasswordCodec(PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1))
            )
            now = datetime.now(UTC)
            grant = accounts.login(
                Credentials("canceller", EXAMPLE_SECRET), now=now, audit=AUDIT_CONTEXT
            )
            service = JobService(
                engine, _registry(self.root, str(_configuration(self.root)["mode"]))
            )
            service.cancel(JobRequest(grant.identity, now, AUDIT_CONTEXT), self.job_id)
        finally:
            engine.dispose()

    def stop(self) -> None:
        """写临时停止握手，子进程夹具将其转换成注入Event，不修改生产信号处理。"""
        heartbeat = _heartbeat(self.root)
        (self.root / f"stop-{heartbeat.pid}-{heartbeat.instance_id}").touch()

    def tool_pid(self) -> int:
        """读已就绪工具的正pid；就绪握手只在SIGTERM忽略处理器安装后产生。"""
        return int((self.root / "tool-pid").read_text())

    def execution_order(self) -> tuple[int, ...]:
        """读取执行顺序握手，恢复作业必须早于新queued作业。"""
        return tuple(int(str(event["job_id"])) for event in _events(self.root))

    def cleanup_orphans(self) -> None:
        """finally读取本夹具登记的worker/工具pid和进程组，有界清理；一个wait超时也继续清理其余对象，不操作无关进程。"""
        pids = (
            [int(value) for value in (self.root / "workers").read_text().splitlines()]
            if (self.root / "workers").exists()
            else []
        )
        if (self.root / "tool-pid").exists():
            pids.append(self.tool_pid())
        for pid in pids:
            try:
                if os.getpgid(pid) == pid:
                    os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                continue
        deadline = time.monotonic() + PROCESS_EXIT_TIMEOUT_S
        for pid in pids:
            while time.monotonic() < deadline:
                try:
                    reaped, _ = os.waitpid(pid, os.WNOHANG)
                    if reaped:
                        break
                except ChildProcessError:
                    break
                Event().wait(0.01)


def prepare_process_case(root: Path, mode: str, command: ToolCommand | None = None) -> ProcessCase:
    """在临时目录迁移0004、建两账号，登记测试专用resume/restart/interrupt/外部进程类型。

    提交测试作业和排在它后面的示例；前三条在一秒内report后写“已上报”握手并进入长reporter.wait，
    父进程wait_running独立读数据库确认第3条真正落库；补写不依赖父进程放行或下一次report。
    claim_gap夹具在claim_job事务提交后、execute_job打开日志前暂停，重启的interrupt模式不再暂停。
    shutdown_timeout类型先确认第3条已持久化，再进入不检查停止的daemon阻塞制造超时；
    该类型提交快照为interrupt，保证第一进程退出后新实例不会再次执行坏函数。正常类型仍遵守检查点。
    外部进程类型通过ExecutionContext.run_process启动command，不借用真实数据或网络。

    Returns:
        含两个作业编号和临时根目录的夹具句柄。
    """
    paths = state_paths(PlatformConfig(state_dir=root), ("示例：数数", "测试作业"))
    initialize_state(paths)
    migrate(paths, now=datetime.now(UTC))
    data = {
        "mode": mode,
        "command": None if command is None else asdict(command) | {"cwd": str(command.cwd)},
    }
    (root / "case.json").write_text(json.dumps(data))
    registry = _registry(root, mode)
    definition = registry.lookup("process_case")
    example = registry.lookup("example_count")
    assert definition is not None and example is not None
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine) as session:
            session.add_all(
                [
                    model_row("submitter", account_id=1, must_change_password=False),
                    model_row("canceller", account_id=2, must_change_password=False),
                ]
            )
            first = insert_job(
                session, NewJob(definition, {}, ActorRef(1, "测试提交人"), datetime.now(UTC), None)
            )
            second = insert_job(
                session,
                NewJob(
                    example,
                    {"steps": 1, "interval_ms": 0},
                    ActorRef(1, "测试提交人"),
                    datetime.now(UTC),
                    None,
                ),
            )
        return ProcessCase(root, first.job_id, second.job_id)
    finally:
        engine.dispose()


def worker_main(root: Path, mode: str) -> None:
    """真实子进程入口：从临时夹具构造引擎/测试登记表/时钟，调用rdp.ops.worker.run_worker。

    不跨进程传Engine；停止握手按实例uuid命名，旧请求不影响新实例；监视线程也有截止且finally回收。锁冲突把入口退出码交sys.exit。
    worker与所有测试工具pid在运行前写root供最终清理，生产依赖systemd control-group，测试不能假设SIGKILL会杀工具。
    shutdown_timeout及reader_timeout模式在入口返回后丢弃结果引用并GC，再最多保活FAILED_WORKER_HOLD_S，等allow_process_exit才以失败码退出，
    以验证返回后原始锁fd仍在；其余模式立即以返回码退出。测试类型不进入production_registry。

    Raises:
        SystemExit: 完成worker退出后把具名退出码交操作系统。
    """
    paths = state_paths(PlatformConfig(state_dir=root), ("示例：数数", "测试作业"))
    engine = create_database_engine(paths.database)
    stop, finished = Event(), Event()
    with (root / "workers").open("a") as stream:
        stream.write(f"{os.getpid()}\n")
    # 测试只缩短主循环及停止预算；生产10秒取消宽限不改。
    policy.WORKER_POLL_INTERVAL_S = 0.02
    if mode in {"shutdown_timeout", "reader_timeout"}:
        policy.WORKER_STOP_TIMEOUT_S = 0.1
    if mode == "claim_gap":
        _hold_claim_gap(root, stop)
    watcher = Thread(target=_watch_stop, args=(root, stop, finished), daemon=True)
    try:
        watcher.start()
        result = run_worker(
            ExecutorDependencies(
                engine,
                _registry(root, mode),
                paths,
                JobClock(lambda: datetime.now(UTC), time.monotonic),
            ),
            stop,
            LoggingSettings("worker", paths.logs),
        )
        recorded, code, retained = asdict(result), result.code, result.lock_retained
        del result
        gc.collect()
        (root / f"gc-{os.getpid()}").touch()
        (root / f"returned-{os.getpid()}.json").write_text(json.dumps(recorded))
        if mode in {"shutdown_timeout", "reader_timeout"} and retained:
            _wait(lambda: (root / f"exit-{os.getpid()}").exists(), FAILED_WORKER_HOLD_S)
        raise SystemExit(code)
    finally:
        try:
            finished.set()
            watcher.join(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            engine.dispose()


class _Parameters(BaseModel):
    """测试类型没有业务参数，也没有口令或令牌字段。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


def _configuration(root: Path) -> dict[str, object]:
    """读取父进程写入的有界测试输入，不接收外部路径。"""
    return cast(dict[str, object], json.loads((root / "case.json").read_text()))


def _registry(root: Path, mode: str) -> JobRegistry:
    """只在夹具登记恢复类型；示例包装只记录执行先后，不改变生产登记表。"""
    registry = JobRegistry()
    example = production_registry().lookup("example_count")
    assert example is not None

    def count(context: ExecutionContext) -> None:
        _record_execution(root, context)
        execute_count(context)

    registry.register(
        JobDefinition(
            example.type_name,
            example.display_name,
            example.parameters_model,
            example.recovery_mode,
            count,
        )
    )
    recovery = RecoveryMode(mode) if mode in {"resume", "restart"} else RecoveryMode.INTERRUPT
    registry.register(
        JobDefinition(
            "process_case",
            "测试作业",
            _Parameters,
            recovery,
            lambda context: _execute_case(root, mode, context),
        )
    )
    return registry


def _record_execution(root: Path, context: ExecutionContext) -> None:
    """写执行握手只供独立断言；数据库落库握手仍通过查询确认。"""
    initial = context.reporter.snapshot().progress
    data = {
        "job_id": context.job_id,
        "mode": context.mode.value,
        "previous": None
        if context.previous_progress is None
        else context.previous_progress.model_dump(),
        "initial": None if initial is None else initial.model_dump(),
    }
    with (root / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(data) + "\n")


def _execute_case(root: Path, mode: str, context: ExecutionContext) -> None:
    """前三次密集上报后真正进入长等待；父进程观察数据库第3条再杀进程。"""
    _record_execution(root, context)
    if context.mode.value != "fresh":
        context.reporter.report(_progress(4))
        return
    for done in (1, 2, 3):
        context.reporter.report(_progress(done))
    if mode == "shutdown_timeout":
        context.reporter.wait(1.05)
        (root / "blocked-ready").touch()
        Event().wait(FAILED_WORKER_HOLD_S)
    elif mode == "reader_timeout":
        context.reporter.wait(1.05)
        # 输出线程的阻塞可独立于执行线程存在；真实进程退出负责终止遗留daemon。
        reader = Thread(target=Event().wait, args=(FAILED_WORKER_HOLD_S,), daemon=True)
        context.reporter.track_output_thread(reader)
        reader.start()
    elif mode in {"lock_inheritance", "term_ignored"}:
        context.run_process(_tool_command(root, mode))
    else:
        context.reporter.wait(60)


def _progress(done: int) -> JobProgress:
    """四条测试作业的累计进度，续跑从3接到4，不用增量冒充总量。"""
    return JobProgress(
        stage_index=1,
        stage_count=1,
        stage_name="测试",
        done=done,
        total=4,
        unit="条",
        total_items=done,
        failed_items=0,
        warning_count=0,
    )


def _tool_command(root: Path, mode: str) -> ToolCommand:
    """启动指定测试命令；只增加PID登记，ready仍由工具安装处理器后打印。"""
    configured = _configuration(root)["command"]
    prelude = f"import os; from pathlib import Path; Path({str(root / 'tool-pid')!r}).write_text(str(os.getpid())); "
    if isinstance(configured, dict):
        data = cast(dict[str, object], configured)
        argv = tuple(str(item) for item in cast(list[object], data["argv"]))
        assert argv[0] == sys.executable and argv[-2] == "-c"
        return ToolCommand(
            str(data["tool_name"]),
            argv[:-1] + (prelude + argv[-1],),
            root,
            float(str(data["timeout_s"])),
        )
    code = (
        prelude
        + "import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('ready',flush=True); time.sleep(60)"
    )
    return ToolCommand("测试工具", (sys.executable, "-u", "-c", code), root, 60.0)


def _record(root: Path, job_id: int) -> JobRecord:
    """每次查询独立受管连接，不能把内存report值冒充已经提交。"""
    engine = create_database_engine(root / "rdp.sqlite3")
    try:
        with session_scope(engine, read_only=True) as session:
            return find_job(session, job_id)
    finally:
        engine.dispose()


def _terminal(root: Path, job_id: int, timeout_s: float) -> JobRecord:
    """终态握手同时保留明确总期限，失败不会悄悄延长。"""
    _wait(
        lambda: (
            _record(root, job_id).state
            in {JobState.COMPLETED, JobState.CANCELLED, JobState.INTERRUPTED}
        ),
        timeout_s,
    )
    return _record(root, job_id)


def _wait(predicate: Callable[[], bool], timeout_s: float) -> None:
    """有界检查独立可见状态，避免固定长sleep制造调度竞争。"""
    deadline = time.monotonic() + timeout_s
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("测试子进程握手超时")
        Event().wait(0.01)


def _log(root: Path, job_id: int) -> str:
    """夹具读完整小日志仅供内容比对；Web的生产尾读仍有字节上限。"""
    record = _record(root, job_id)
    if record.log_path is None:
        return ""
    path = root / record.log_path
    return path.read_text() if path.exists() else ""


def _events(root: Path) -> list[dict[str, object]]:
    """一次执行一个完整JSON行；读取只发生在终态或明确握手之后。"""
    return [
        cast(dict[str, object], json.loads(line))
        for line in (root / "events.jsonl").read_text().splitlines()
    ]


def _heartbeat(root: Path) -> WorkerHeartbeatRow:
    """以数据库中的实例号定位停止文件，不让旧实例请求停止新worker。"""
    engine = create_database_engine(root / "rdp.sqlite3")
    try:
        with session_scope(engine, read_only=True) as session:
            heartbeat = session.get(WorkerHeartbeatRow, 1)
            assert heartbeat is not None
            return heartbeat
    finally:
        engine.dispose()


def _watch_stop(root: Path, stop: Event, finished: Event) -> None:
    """监听仅本进程实例的停止文件，有限总期限且finally回收监视线程。"""
    deadline = time.monotonic() + FAILED_WORKER_HOLD_S
    while not finished.wait(0.01) and time.monotonic() < deadline:
        try:
            heartbeat = _heartbeat(root)
        except AssertionError:
            continue
        if (
            heartbeat.pid == os.getpid()
            and (root / f"stop-{heartbeat.pid}-{heartbeat.instance_id}").exists()
        ):
            stop.set()


def _hold_claim_gap(root: Path, stop: Event) -> None:
    """仅子进程夹具在真实领取提交后的执行入口暂停，暴露崩溃窗口。"""
    from rdp.jobs import _loop

    original = _loop.execute_job

    def held(
        work: ExecutionWork, dependencies: ExecutorDependencies, signals: ExecutionSignals
    ) -> JobRecord | None:
        (root / "claim-gap").touch()
        stop.wait(FAILED_WORKER_HOLD_S)
        return original(work, dependencies, signals)

    _loop.execute_job = held
