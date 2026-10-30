"""作业存储边界契约清单（10、验收3），使用测试专用作业类型。"""

import inspect
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread, current_thread
from typing import cast
from unittest.mock import Mock

import pytest
from jobs_execution_support import execution_case
from jobs_gpu_support import signals_fixture
from jobs_scheduling_execution_support import scheduling_case
from jobs_storage_support import NOW

from rdp.infra.config import StorageConfig, StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError, DiagnosticCategory, ExternalError
from rdp.infra.storage import DeviceNumber, MountInspector, StorageAccessChecker, read_storage_root
from rdp.jobs.execution import ExecutionContext, ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.progress import ExecutionSignals
from rdp.jobs.records import StateChange, transition_job
from rdp.jobs.registry import JobRegistry, StorageUse, production_registry
from rdp.jobs.storage import check_storage_before_job
from rdp.jobs.types import ExecutionMode, JobRecord, JobState

UUID = "12345678-1234-1234-1234-123456789abc"


def _checker(tmp_path: Path, *, writable: bool = False) -> StorageAccessChecker:
    """只对临时根访问，挂载身份由独立合成记录提供。"""
    root = tmp_path / "disk"
    root.mkdir(parents=True)
    config = StorageRootConfig(name="disk", path=root, uuid=UUID, writable=writable)
    table = f"20 1 8:1 / {root} rw - ext4 /dev/alias rw\n"
    return StorageAccessChecker(
        MountInspector((config,), lambda: table, lambda _: DeviceNumber(8, 1), lambda: NOW),
        StorageConfig(access_timeout_s=0.1),
        read_storage_root,
    )


def _dependencies(
    dependencies: ExecutorDependencies,
    uses: tuple[StorageUse, ...],
    checker: StorageAccessChecker | None,
) -> ExecutorDependencies:
    """用公开登记接口替换测试类型声明，保留真实执行资源和数据库。"""
    definition = dependencies.registry.lookup("example_count")
    assert definition is not None
    registry = JobRegistry()
    registry.register(replace(definition, storage=uses))
    return replace(dependencies, registry=registry, storage=checker)


def test_readonly_write_fails(tmp_path: Path) -> None:
    """验收3：声明写只读根以ExternalError和失败结果收尾，诊断含根名、实际只读、期望、后果和下一步，execute调用为零且假根无新文件。"""
    checker = _checker(tmp_path)
    execute = Mock(return_value=None)
    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        result = execute_job(
            work, _dependencies(deps, (StorageUse("disk", True),), checker), signals
        )
    assert (
        result is not None
        and result.summary is not None
        and result.summary.outcome is JobOutcome.FAILED
    )
    diagnostic = result.diagnostics[0].samples[0]
    assert (
        diagnostic.category is DiagnosticCategory.EXTERNAL
        and diagnostic.rule == "storage.read_only"
    )
    assert any(item.key == "storage_root" and item.value == "disk" for item in diagnostic.objects)
    assert (
        "只读" in diagnostic.actual
        and diagnostic.expected
        and diagnostic.consequence
        and diagnostic.next_step
    )
    execute.assert_not_called()
    assert list((tmp_path / "disk").iterdir()) == []


@pytest.mark.parametrize(
    ("reason", "label"),
    [("not_mounted", "没挂载"), ("source_mismatch", "挂错了盘"), ("timeout", "超时")],
)
def test_offline_fails(tmp_path: Path, reason: str, label: str) -> None:
    """验收3：声明根没挂载、挂错盘、超时均以外部失败结束，根名和原因入统一诊断，execute调用为零且假根无新文件。"""
    checker = _checker(tmp_path / reason)
    release = Event()
    threads: list[Thread] = []

    def blocked() -> str:
        threads.append(current_thread())
        assert release.wait(2)
        return ""

    if reason == "not_mounted":
        checker = replace(checker, mounts=replace(checker.mounts, read_mountinfo=lambda: ""))
    elif reason == "source_mismatch":
        checker = replace(
            checker,
            mounts=replace(checker.mounts, resolve_uuid_device=_other_device),
        )
    else:
        checker = replace(checker, mounts=replace(checker.mounts, read_mountinfo=blocked))
    execute = Mock(return_value=None)
    try:
        with execution_case(
            tmp_path / reason / "state", {"steps": 1, "interval_ms": 0}, execute
        ) as (work, deps, signals):
            result = execute_job(work, _dependencies(deps, (StorageUse("disk"),), checker), signals)
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome is JobOutcome.FAILED
        )
        diagnostic = result.diagnostics[0].samples[0]
        assert (
            diagnostic.category is DiagnosticCategory.EXTERNAL
            and diagnostic.rule == "storage.offline"
        )
        assert diagnostic.actual == label
        assert any(
            item.key == "storage_root" and item.value == "disk" for item in diagnostic.objects
        )
        execute.assert_not_called()
        assert list(checker.mounts.roots[0].path.iterdir()) == []
    finally:
        release.set()
        for thread in threads:
            thread.join(1)
            assert not thread.is_alive()


def test_no_storage_skips_checks(tmp_path: Path) -> None:
    """验证十种生产类型storage默认空，无声明的作业不读挂载表、不查UUID、不stat根、不读检查时钟。"""
    definitions = production_registry().definitions()
    assert len(definitions) == 10 and all(item.storage == () for item in definitions)
    forbidden = Mock(side_effect=AssertionError("不应访问存储"))
    checker = replace(
        _checker(tmp_path),
        mounts=MountInspector((), forbidden, forbidden, forbidden),
        access=forbidden,
    )
    execute = Mock(return_value=None)
    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        result = execute_job(work, replace(deps, storage=checker), signals)
    assert (
        result is not None
        and result.summary is not None
        and result.summary.outcome is JobOutcome.SUCCEEDED
    )
    execute.assert_called_once()
    forbidden.assert_not_called()


def test_read_only_use_succeeds(tmp_path: Path) -> None:
    """验证只读根的读声明允许执行，可写根的写声明通过检查后执行恰好一次。"""
    for writable in (False, True):
        root = tmp_path / str(writable)
        checker = _checker(root, writable=writable)
        probe = Mock(wraps=read_storage_root)
        execute = Mock(return_value=None)
        with execution_case(root / "state", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            deps,
            signals,
        ):
            result = execute_job(
                work,
                _dependencies(
                    deps, (StorageUse("disk", writable),), replace(checker, access=probe)
                ),
                signals,
            )
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome is JobOutcome.SUCCEEDED
        )
        probe.assert_called_once_with(root / "disk")
        execute.assert_called_once()


def test_unknown_registration_rejected(tmp_path: Path) -> None:
    """验证全部登记完成后的validate_storage_roots拒绝未知根，诊断含类型名和根名，Web/worker不得启动。"""
    registry = JobRegistry()
    definition = production_registry().definitions()[0]
    registry.register(replace(definition, storage=(StorageUse("missing"),)))
    with pytest.raises(ValueError) as caught:
        registry.validate_storage_roots(roots=_checker(tmp_path).mounts.roots)
    message = str(caught.value)
    assert definition.type_name in message and "missing" in message and "拒绝启动" in message
    production_registry().validate_storage_roots(roots=())


def test_invalid_declarations() -> None:
    """验证storage非元组、成员非法、根名非法/重复及write非bool在类型登记时被拒绝。"""
    definition = production_registry().definitions()[0]
    for value in (
        [StorageUse("disk")],
        (object(),),
        (StorageUse("bad/path"),),
        (StorageUse("disk"), StorageUse("disk")),
        (StorageUse("disk", cast(bool, 1)),),
    ):
        registry = JobRegistry()
        with pytest.raises(DefectError):
            registry.register(replace(definition, storage=cast(tuple[StorageUse, ...], value)))
        assert registry.definitions() == ()


def test_all_permissions_before_io(tmp_path: Path) -> None:
    """验证多个声明里任何只读违规在所有挂载检查前失败，不因靠后违规而先访问别的根。"""
    checker = _checker(tmp_path)
    second = StorageRootConfig(name="second", path=tmp_path / "second", uuid=UUID, writable=True)
    forbidden = Mock(side_effect=AssertionError("只读违规前不读系统"))
    checker = replace(
        checker,
        mounts=replace(
            checker.mounts, roots=(second, *checker.mounts.roots), read_mountinfo=forbidden
        ),
    )
    with pytest.raises(ExternalError) as caught:
        check_storage_before_job(
            (StorageUse("second"), StorageUse("disk", True)),
            checker=checker,
            checkpoint=lambda: None,
        )
    assert caught.value.diagnostics[0].rule == "storage.read_only"
    forbidden.assert_not_called()


def test_first_failure_stops(tmp_path: Path) -> None:
    """验证按声明顺序检查而非配置顺序；第一根离线后不再检查后续根，函数不执行。"""
    checker = _checker(tmp_path)
    second = StorageRootConfig(name="second", path=tmp_path / "second", uuid=UUID)
    read = Mock(return_value="")
    access = Mock(return_value=None)
    checker = replace(
        checker,
        mounts=replace(checker.mounts, roots=(*checker.mounts.roots, second), read_mountinfo=read),
        access=access,
    )
    with pytest.raises(ExternalError) as caught:
        check_storage_before_job(
            (StorageUse("second"), StorageUse("disk")), checker=checker, checkpoint=lambda: None
        )
    assert caught.value.diagnostics[0].objects[0].value == "second"
    read.assert_called_once_with()
    access.assert_not_called()


def test_infrastructure_failure(tmp_path: Path) -> None:
    """验证表读取/解析、UUID和根stat的ExternalError在执行器外层收口，统一诊断保留原规则和根名。"""
    for stage in ("table", "parse", "uuid", "access"):
        checker = _checker(tmp_path / stage)
        failing = Mock(side_effect=OSError(5, "io"))
        if stage in {"table", "parse"}:
            checker = replace(
                checker,
                mounts=replace(
                    checker.mounts, read_mountinfo=failing if stage == "table" else lambda: "broken"
                ),
            )
        elif stage == "uuid":
            checker = replace(checker, mounts=replace(checker.mounts, resolve_uuid_device=failing))
        else:
            checker = replace(checker, access=failing)
        execute = Mock(return_value=None)
        with execution_case(
            tmp_path / stage / "state", {"steps": 1, "interval_ms": 0}, execute
        ) as (work, deps, signals):
            result = execute_job(work, _dependencies(deps, (StorageUse("disk"),), checker), signals)
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome is JobOutcome.FAILED
        )
        diagnostic = result.diagnostics[0].samples[0]
        expected = (
            "storage.mount_table"
            if stage in {"table", "parse"}
            else "storage.uuid_device"
            if stage == "uuid"
            else "storage.access"
        )
        assert diagnostic.rule == expected and diagnostic.category is DiagnosticCategory.EXTERNAL
        assert any(
            item.key == "storage_root" and item.value == "disk" for item in diagnostic.objects
        )
        execute.assert_not_called()


def test_required_dependencies() -> None:
    """验证存储依赖、登记根集合和两层checkpoint均为无默认值必填关键字。"""
    for target, name in (
        (ExecutorDependencies, "storage"),
        (check_storage_before_job, "checker"),
        (check_storage_before_job, "checkpoint"),
        (StorageAccessChecker.check, "checkpoint"),
        (JobRegistry.validate_storage_roots, "roots"),
    ):
        parameter = inspect.signature(target).parameters[name]
        assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
        assert parameter.default is inspect.Parameter.empty


def test_missing_checker() -> None:
    """验证非空声明配显式None检查器为DefectError，空声明配None合法且无I/O。"""
    with pytest.raises(DefectError):
        check_storage_before_job((StorageUse("disk"),), checker=None, checkpoint=lambda: None)
    assert check_storage_before_job((), checker=None, checkpoint=lambda: None) is None


def test_recovery_rechecks(tmp_path: Path) -> None:
    """验证fresh/resume/restart都在类型调用前重新检查，不信任旧检查或网页状态。"""
    for mode in ExecutionMode:
        checker = _checker(tmp_path / mode.value)
        assert checker.mounts.inspect()[0].online
        checker = replace(checker, mounts=replace(checker.mounts, read_mountinfo=lambda: ""))
        execute = Mock(return_value=None)
        with execution_case(
            tmp_path / mode.value / "state", {"steps": 1, "interval_ms": 0}, execute
        ) as (work, deps, signals):
            result = execute_job(
                replace(work, mode=mode),
                _dependencies(deps, (StorageUse("disk"),), checker),
                signals,
            )
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome is JobOutcome.FAILED
        )
        assert result.diagnostics[0].samples[0].rule == "storage.offline"
        execute.assert_not_called()


@pytest.mark.parametrize("action", ["cancel", "stop"])
@pytest.mark.parametrize("before", [False, True])
def test_cancel_and_stop(tmp_path: Path, action: str, before: bool) -> None:
    """验证检查前后遵守取消和停止检查点，检查期间取消仍按既有终态优先规则收尾且不执行类型函数。"""
    checker = _checker(tmp_path)
    execute = Mock(return_value=None)
    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):

        def change() -> None:
            """通过公共状态转换提交取消，或置入口停止信号。"""
            if action == "cancel":
                with session_scope(deps.engine) as session:
                    transition_job(
                        session,
                        work.record.job_id,
                        StateChange(JobState.RUNNING, JobState.CANCELLING, NOW),
                    )
                signals.cancelled.set()
            else:
                signals.stopping.set()

        def access(_path: Path) -> None:
            change()

        probe = Mock(side_effect=access)
        if before:
            change()
        result = execute_job(
            work,
            _dependencies(deps, (StorageUse("disk"),), replace(checker, access=probe)),
            signals,
        )
        assert (
            (result is not None and result.state is JobState.CANCELLED)
            if action == "cancel"
            else result is None
        )
        assert probe.call_count == (0 if before else 1)
        execute.assert_not_called()


def test_outside_transactions_and_lock(tmp_path: Path) -> None:
    """验证存储等待不持数据库事务或导航层写锁，失败不阻止其他类型作业继续执行。"""
    checker = _checker(tmp_path)
    entered, release, other_done = Event(), Event(), Event()
    results: list[object] = []

    def access(_path: Path) -> None:
        entered.set()
        assert release.wait(2)
        raise OSError(5, "failed")

    def execute(context: ExecutionContext) -> None:
        assert context.job_id == 72
        context.write_navigation(lambda: None, other_done.set)

    with scheduling_case(tmp_path / "state", execute=execute) as case:
        registry = JobRegistry()
        for definition in case.dependencies.registry.definitions():
            registry.register(
                replace(
                    definition, storage=(StorageUse("disk"),) if definition.type_name == "a" else ()
                )
            )
        deps = replace(
            case.dependencies,
            registry=registry,
            storage=replace(checker, access=access, options=StorageConfig(access_timeout_s=1)),
        )
        case.add(71, "a")
        case.add(72, "b")
        first = case.scheduler.claim_next()
        assert first is not None
        signals = signals_fixture()
        thread = Thread(
            target=lambda: results.append(execute_job(first, deps, signals)), daemon=True
        )
        thread.start()
        try:
            assert entered.wait(1)
            second = case.scheduler.claim_next()
            assert second is not None
            result = execute_job(second, deps, signals_fixture())
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome is JobOutcome.SUCCEEDED
            )
            assert other_done.is_set()
            assert thread.is_alive(), "另一类型必须在存储检查返回之前完成"
        finally:
            release.set()
            signals.stopping.set()
            thread.join(2)
            assert not thread.is_alive()
        assert len(results) == 1


def test_preflight_invalid_inputs(tmp_path: Path) -> None:
    """直接调用公开前置检查时也拒绝坏形状、重复需求与未登记根，不依赖调用者已经校验。"""
    checker = _checker(tmp_path)
    for uses in (
        list[StorageUse](),
        (object(),),
        (StorageUse("disk"), StorageUse("disk")),
        (StorageUse("unknown"),),
    ):
        with pytest.raises(DefectError):
            check_storage_before_job(
                cast(tuple[StorageUse, ...], uses), checker=checker, checkpoint=lambda: None
            )
    with pytest.raises(DefectError):
        check_storage_before_job(
            (StorageUse("disk"),),
            checker=cast(StorageAccessChecker, object()),
            checkpoint=lambda: None,
        )


def _other_device(_uuid: str) -> DeviceNumber:
    """用不同设备号模拟挂错盘，不查真实设备。"""
    return DeviceNumber(8, 2)


@pytest.mark.parametrize("action", ["stop", "cancel"])
def test_waiting_storage_check_obeys_control_signal(tmp_path: Path, action: str) -> None:
    """十秒访问仍阻塞时，停止或取消须在0.75秒内结束等待，迟到访问不能执行作业或改变结局。"""
    entered, release, completed = Event(), Event(), Event()
    readers: list[Thread] = []
    outcomes: list[object] = []
    errors: list[Exception] = []
    execute = Mock(return_value=None)

    def access(_path: Path) -> None:
        """真实内核等待的可释放替身，清理始终有界。"""
        readers.append(current_thread())
        entered.set()
        assert release.wait(3)

    checker = replace(_checker(tmp_path), access=access, options=StorageConfig(access_timeout_s=10))
    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):

        def run() -> None:
            try:
                outcomes.append(
                    execute_job(work, _dependencies(deps, (StorageUse("disk"),), checker), signals)
                )
            except Exception as error:
                errors.append(error)
            finally:
                completed.set()

        caller = Thread(target=run, daemon=True)
        caller.start()
        try:
            assert entered.wait(1)
            _request_control(work, deps, signals, action)
            assert completed.wait(0.75), "停止/取消不能等满访问超时"
            assert not errors and len(outcomes) == 1
            if action == "stop":
                assert outcomes[0] is None
            else:
                assert (
                    isinstance(outcomes[0], JobRecord) and outcomes[0].state is JobState.CANCELLED
                )
            execute.assert_not_called()
            assert readers[0].is_alive()
            assert list((tmp_path / "disk").iterdir()) == []
        finally:
            _release_readers(caller, readers, release)
        assert len(outcomes) == 1
        execute.assert_not_called()


def _request_control(
    work: ExecutionWork, dependencies: ExecutorDependencies, signals: ExecutionSignals, action: str
) -> None:
    """真实提交取消状态后置控制信号，停止则沿用入口Event。"""
    if action == "cancel":
        with session_scope(dependencies.engine) as session:
            transition_job(
                session, work.record.job_id, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
            )
        signals.cancelled.set()
    else:
        signals.stopping.set()


def _release_readers(caller: Thread, readers: list[Thread], release: Event) -> None:
    """先释放阻塞回调，再逐个有界回收调用线程与读取线程。"""
    release.set()
    caller.join(2)
    for reader in readers:
        reader.join(2)
        assert not reader.is_alive()
    assert not caller.is_alive()
