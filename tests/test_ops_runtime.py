"""第 11 张 runtime 契约清单；只用临时目录和可注入依赖，不触碰真实部署或服务。"""

import sqlite3
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from ops_support import NOW, runtime_inputs
from sqlalchemy import Engine, event

from rdp.infra.diagnostics import DefectError, ExternalError, InputError
from rdp.jobs.registry import JobRegistry, StorageUse, production_registry
from rdp.jobs.types import JobClock
from rdp.ops import runtime as runtime_module
from rdp.ops.runtime import prepare_service, resolve_nvidia_smi


def test_assembly_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：load_config→状态目录→日志→来源/权限警告→引擎/版本→完整注册表/存储校验→调度/挂载的顺序可观察。"""
    inputs = runtime_inputs(tmp_path)
    observed: list[str] = []
    connect = sqlite3.connect

    def connected(*args: object, **kwargs: object) -> object:
        log = inputs.home / "state/logs/web.log"
        assert log.is_file()
        assert "config.toml" in log.read_text()
        observed.append("connect")
        return Mock(wraps=connect)(*args, **kwargs)

    monkeypatch.setattr(sqlite3, "connect", connected)
    runtime = prepare_service("web", no_stderr=True, inputs=inputs)
    try:
        assert observed
        assert runtime.logging.stderr is False
        assert len(runtime.registry.definitions()) == 10
        assert len(runtime.scheduling.schedules.definitions()) == 3
        assert all(path.is_dir() for _, path in runtime.paths.job_logs)
        assert runtime.version == "0.1.0 (aaaaaaa)"
    finally:
        runtime.engine.dispose()


def test_configuration_source(tmp_path: Path) -> None:
    """验证契约：RDP_CONFIG 与 home 替身决定最终配置；未知项或缺指定文件拒绝，日志不输出整份环境。"""
    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service(
        "web",
        no_stderr=True,
        inputs=replace(inputs, environ={**inputs.environ, "SECRET_ENV": "must-not-log"}),
    )
    runtime.engine.dispose()
    text = (runtime.paths.logs / "web.log").read_text()
    assert str(tmp_path / "config.toml") in text and "must-not-log" not in text
    assert runtime.paths.root == inputs.home / "state"
    (tmp_path / "config.toml").write_text("unknown = 1")
    with pytest.raises(ValueError):
        prepare_service("web", no_stderr=True, inputs=inputs)
    (tmp_path / "config.toml").unlink()
    with pytest.raises(FileNotFoundError):
        prepare_service("web", no_stderr=True, inputs=inputs)


def test_directory_failure(tmp_path: Path) -> None:
    """验证契约：状态路径被文件占用或不可写时拒绝，不启动服务；宽权限目录只记警告，不自动 chmod。"""
    inputs = runtime_inputs(tmp_path / "blocked", migrated=False)
    (inputs.home / "state").write_text("占用路径")
    with pytest.raises(NotADirectoryError):
        prepare_service("web", no_stderr=True, inputs=inputs)
    inputs = runtime_inputs(tmp_path / "wide")
    state = inputs.home / "state"
    state.chmod(0o755)
    runtime = prepare_service("web", no_stderr=True, inputs=inputs)
    runtime.engine.dispose()
    assert state.stat().st_mode & 0o777 == 0o755
    text = (state / "logs/web.log").read_text()
    assert text.count("状态目录权限宽于") == 1


def test_registry_storage_validation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：验收装配：作业声明的根名字未登记时拒绝启动，验证发生在全部类型注册之后。"""
    inputs = runtime_inputs(tmp_path)
    registry = JobRegistry()
    for definition in production_registry().definitions():
        registry.register(replace(definition, storage=(StorageUse("missing", False),)))

    def configured_registry(
        _dependencies: object = None, _navigation_write: object = None
    ) -> JobRegistry:
        return registry

    monkeypatch.setattr(runtime_module, "production_registry", configured_registry)
    with pytest.raises(InputError):
        prepare_service("web", no_stderr=True, inputs=inputs)


def test_scheduling_catalog(tmp_path: Path) -> None:
    """验证契约：Web/worker 均使用 resolve_scheduling、production_schedules 及注入本地规则时区；非法并发配置拒绝。"""
    inputs = runtime_inputs(tmp_path)
    config = tmp_path / "config.toml"
    config.write_text(config.read_text() + "[jobs.concurrency]\nexample_count = 3\n")
    for process in ("web", "worker"):
        runtime = prepare_service(process, no_stderr=True, inputs=inputs)
        try:
            settings = runtime.scheduling.settings
            assert settings.gpus == ()
            assert (
                next(
                    item.concurrency for item in settings.types if item.type_name == "example_count"
                )
                == 3
            )
            assert len(runtime.scheduling.schedules.definitions()) == 3
        finally:
            runtime.engine.dispose()
    config.write_text(config.read_text().replace("example_count = 3", "unknown_type = 3"))
    with pytest.raises(InputError):
        prepare_service("web", no_stderr=True, inputs=inputs)


def test_storage_inspector(tmp_path: Path) -> None:
    """验证契约：Web 只装配 MountInspector 的挂载表和 UUID 回调，不运行 read_storage_root 或触碰存储内容。"""
    inputs = runtime_inputs(tmp_path)
    # 删除挂载表后仍可装配，说明启动没有提前探测系统或存储内容。
    (tmp_path / "mountinfo").unlink()
    runtime = prepare_service("web", no_stderr=True, inputs=inputs)
    try:
        assert runtime.inspector.roots == ()
        assert runtime.inspector.inspect() == ()
        assert runtime.inspector.read_mountinfo == inputs.mounts.read_mountinfo
        assert runtime.inspector.resolve_uuid_device == inputs.mounts.resolve_uuid_device
    finally:
        runtime.engine.dispose()


def test_worker_storage_checker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：worker 必须把 StorageAccessChecker(config.storage, inspector, read_storage_root) 传入 ExecutorDependencies。"""
    from contextlib import nullcontext

    from rdp.infra.storage import StorageAccessChecker, read_storage_root
    from rdp.ops import lifecycle
    from rdp.ops.worker import WorkerExit

    inputs = runtime_inputs(tmp_path)
    runtime = prepare_service("worker", no_stderr=True, inputs=inputs)
    runner = Mock(return_value=WorkerExit(0, "已停止", False))
    monkeypatch.setattr(lifecycle, "run_worker", runner)
    assert lifecycle.start_worker(runtime, inputs=inputs, signals=lambda _: nullcontext()) == 0
    dependencies = runner.call_args.args[0]
    assert isinstance(dependencies.storage, StorageAccessChecker)
    assert dependencies.storage.mounts is runtime.inspector
    assert dependencies.storage.options is runtime.loaded.config.storage
    assert dependencies.storage.access is read_storage_root
    assert dependencies.platform_version == runtime.version


def test_version_snapshot(tmp_path: Path) -> None:
    """验证契约：服务只读取一次版本；修改构建文件不会改变已运行实例或该实例领取的作业版本。"""
    inputs = runtime_inputs(tmp_path)
    provider = Mock(return_value="0.1.0")
    runtime = prepare_service(
        "web", no_stderr=True, inputs=replace(inputs, package_version=provider)
    )
    try:
        inputs.layout.build_info.write_text('{"commit":"' + "b" * 40 + '"}')
        assert runtime.version == "0.1.0 (aaaaaaa)"
        provider.assert_called_once_with("rdp")
    finally:
        runtime.engine.dispose()


def test_cleanup_partial_failure(tmp_path: Path) -> None:
    """验证契约：引擎创建后注册表、时区或版本失败时 dispose 一次，保留已建目录/日志，运行器不调用。"""
    inputs = runtime_inputs(tmp_path)
    disposed: list[Engine] = []

    def record_disposal(engine: Engine) -> None:
        disposed.append(engine)

    event.listen(Engine, "engine_disposed", record_disposal)
    try:
        inputs.localtime.unlink()
        with pytest.raises(ExternalError):
            prepare_service("web", no_stderr=True, inputs=inputs)
        assert len(disposed) == 1
        assert (inputs.home / "state/logs/web.log").is_file()
    finally:
        event.remove(Engine, "engine_disposed", record_disposal)


def test_clock_invalid(tmp_path: Path) -> None:
    """验证契约：JobClock 的 naive、非有限单调值或回调异常属于 DefectError，不伪装用户输入问题。"""
    inputs = runtime_inputs(tmp_path)
    for clock in (
        JobClock(lambda: NOW.replace(tzinfo=None), lambda: 1.0),
        JobClock(lambda: NOW, lambda: float("nan")),
        JobClock(Mock(side_effect=RuntimeError("clock fault")), lambda: 1.0),
    ):
        with pytest.raises(DefectError):
            prepare_service("web", no_stderr=True, inputs=replace(inputs, clock=clock))


def test_gpu_path_found(tmp_path: Path) -> None:
    """验证契约：配置卡非空时通过注入 which 定位绝对 nvidia-smi，worker 不猜 /usr/bin 路径。"""
    inputs = runtime_inputs(tmp_path)
    path = tmp_path / "工具/nvidia-smi"
    which = Mock(return_value=str(path))
    assert resolve_nvidia_smi(replace(inputs, which=which), gpus=(0,)) == path
    which.assert_called_once_with("nvidia-smi")


def test_gpu_missing_or_relative(tmp_path: Path) -> None:
    """验证契约：配置卡非空但 which 返回 None/相对路径时拒绝并提示修复工具或设置 gpus=[]，不启动 worker。"""
    inputs = runtime_inputs(tmp_path)
    for path in (None, "bin/nvidia-smi"):
        with pytest.raises(InputError) as caught:
            resolve_nvidia_smi(replace(inputs, which=Mock(return_value=path)), gpus=(0,))
        assert "gpus=[]" in caught.value.diagnostics[0].next_step


def test_gpu_empty(tmp_path: Path) -> None:
    """验证契约：配置 gpus=[] 时 nvidia_smi=None，不调用 which，不探测 GPU，CPU 作业仍可运行。"""
    inputs = runtime_inputs(tmp_path)
    which = Mock(side_effect=AssertionError("不应查PATH"))
    assert resolve_nvidia_smi(replace(inputs, which=which), gpus=()) is None
    which.assert_not_called()


def test_gpu_lookup_faults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证契约：命令定位 I/O 归 ExternalError，回调异常/错误类型归 DefectError，释放已创建的引擎。"""
    inputs = runtime_inputs(tmp_path)
    for which in (Mock(side_effect=RuntimeError("坏回调")), Mock(return_value=7)):
        with pytest.raises(DefectError):
            resolve_nvidia_smi(replace(inputs, which=which), gpus=(0,))
    with monkeypatch.context() as patch:
        patch.setattr(Path, "resolve", Mock(side_effect=PermissionError("路径故障")))
        with pytest.raises(ExternalError):
            resolve_nvidia_smi(
                replace(inputs, which=Mock(return_value=str(tmp_path / "gpu"))), gpus=(0,)
            )
