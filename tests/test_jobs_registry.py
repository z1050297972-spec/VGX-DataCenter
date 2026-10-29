"""M0/08 公共契约测试；数据库与文件只使用临时目录，不依赖真实数据或默认状态目录。"""

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from jobs_execution_support import execution_case
from jobs_progress_support import saved_record
from jobs_scheduling_support import resources_fixture
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretBytes,
    SecretStr,
    ValidationError,
    create_model,
)

from rdp.infra.diagnostics import DefectError
from rdp.jobs.example import CountParameters, execute_count
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.registry import JobDefinition, JobRegistry, production_registry
from rdp.jobs.types import RecoveryMode


class _Parameters(BaseModel):
    """测试登记的无秘密参数，不调用执行函数。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    value: int = 1


def _execute(_context: ExecutionContext) -> None:
    """登记测试不执行任何作业。"""


def test_explicit_registry() -> None:
    """类型登记：两个入口与两个测试实例互不污染，没有模块级可变单例。"""
    first, second = JobRegistry(), JobRegistry()
    beta = JobDefinition("beta", "测试乙", _Parameters, RecoveryMode.RESUME, _execute)
    alpha = JobDefinition("alpha", "测试甲", _Parameters, RecoveryMode.RESTART, _execute)
    first.register(beta)
    first.register(alpha)
    assert first.definitions() == (alpha, beta)
    assert first.lookup("beta") is beta
    assert first.lookup("absent") is None
    assert second.definitions() == ()
    assert second.lookup("beta") is None
    second.register(beta)
    assert first.definitions() == (alpha, beta)
    assert second.definitions() == (beta,)


def test_production_example_only() -> None:
    """类型登记：生产六类仍包含独立的 example_count/示例：数数，恢复方式 interrupt。"""
    first, second = production_registry(), production_registry()
    assert first is not second
    definitions = first.definitions()
    assert len(definitions) == 6
    definition = first.lookup("example_count")
    assert definition is not None
    assert (definition.type_name, definition.display_name, definition.recovery_mode) == (
        "example_count",
        "示例：数数",
        RecoveryMode.INTERRUPT,
    )
    assert definition.parameters_model is CountParameters
    assert definition.execute is execute_count
    first.register(JobDefinition("test", "测试专用", _Parameters, RecoveryMode.RESTART, _execute))
    assert second.lookup("test") is None


def test_directory_names() -> None:
    """登记契约：拒绝空白、斜杠、反斜杠、控制字符、点目录、重复显示名和41码点；40码点接受。"""
    registry = JobRegistry()
    valid = JobDefinition("valid", "数" * 40, _Parameters, RecoveryMode.RESUME, _execute)
    registry.register(valid)
    assert registry.lookup("valid") == valid
    for name in (
        "",
        " ",
        " 首",
        "尾 ",
        ".",
        "..",
        "路径/分量",
        "路径\\分量",
        "控制\n符",
        "控制\x00符",
        "数" * 41,
    ):
        with pytest.raises(DefectError):
            registry.register(replace(valid, type_name="invalid", display_name=name))
        assert registry.definitions() == (valid,)
    with pytest.raises(DefectError):
        registry.register(replace(valid, type_name="same_name"))
    assert registry.definitions() == (valid,)


def test_stable_keys() -> None:
    """登记契约：英文键64字符边界与重复键；未知合法键返回None、错误形状DefectError。"""
    registry = JobRegistry()
    valid = JobDefinition("a" * 64, "合法", _Parameters, RecoveryMode.RESTART, _execute)
    registry.register(valid)
    assert registry.lookup("a" * 64) is valid
    assert registry.lookup("absent") is None
    with pytest.raises(DefectError):
        registry.register(replace(valid, display_name="重复键"))
    for key in (
        "",
        "A",
        "0key",
        "a-b",
        "a.b",
        "a/b",
        "a\n",
        "a" * 65,
        cast(str, None),
        cast(str, 1),
    ):
        with pytest.raises(DefectError):
            registry.lookup(key)
        with pytest.raises(DefectError):
            registry.register(replace(valid, type_name=key, display_name="坏键"))
        assert registry.definitions() == (valid,)
    with pytest.raises(DefectError):
        registry.register(cast(JobDefinition, object()))


def test_secret_models() -> None:
    """规范6.10：拒绝秘密字段（含别名/嵌套）及秘密类型；配置、恢复枚举和执行函数非法均原子拒绝。"""
    registry = JobRegistry()
    valid = JobDefinition("safe", "安全参数", _Parameters, RecoveryMode.RESUME, _execute)
    models = [
        create_model("PasswordField", __base__=_Parameters, password=(str, "")),
        create_model("SecretString", __base__=_Parameters, value=(SecretStr, ...)),
        create_model("SecretBytes", __base__=_Parameters, value=(SecretBytes, ...)),
        create_model("SecretList", __base__=_Parameters, value=(list[SecretStr], ...)),
        create_model("SecretAlias", __base__=_Parameters, value=(str, Field(alias="token"))),
        create_model(
            "UnknownFields", __config__=ConfigDict(extra="allow", hide_input_in_errors=True)
        ),
        create_model(
            "ExposedValues", __config__=ConfigDict(extra="forbid", hide_input_in_errors=False)
        ),
    ]
    models.append(create_model("NestedSecret", __base__=_Parameters, child=(models[0], ...)))
    for model in models:
        with pytest.raises(DefectError):
            registry.register(replace(valid, parameters_model=model))
        assert registry.definitions() == ()
    for invalid in (
        replace(valid, parameters_model=cast(type[BaseModel], int)),
        replace(valid, parameters_model=cast(type[BaseModel], object())),
        replace(valid, recovery_mode=cast(RecoveryMode, "resume")),
        replace(valid, execute=cast(Callable[[ExecutionContext], None], None)),
    ):
        with pytest.raises(DefectError):
            registry.register(invalid)
        assert registry.definitions() == ()
    registry.register(valid)
    assert registry.definitions() == (valid,)


def test_unknown_queued_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """升级兼容：未登记类型照常queued→running→completed失败，诊断含类型/实际/后果，worker继续下一作业。"""
    _incompatible_queue(tmp_path, monkeypatch, missing=True)


def test_obsolete_parameters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """升级兼容：历史参数按当前模型无效也领取并失败结束，诊断不回显载荷、不退出worker。"""
    _incompatible_queue(tmp_path, monkeypatch, missing=False)


def test_count_parameter_bounds() -> None:
    """示例契约：步数1/10000、间隔0/60000合法；越界、bool、浮点、重复/越界序号和多余字段拒绝。"""
    for steps, interval in ((1, 0), (10000, 60000)):
        model = CountParameters(
            steps=steps,
            interval_ms=interval,
            failed_steps=(steps,),
            warning_steps=(steps,),
            abort_at_step=steps,
        )
        assert (
            model.steps,
            model.interval_ms,
            model.failed_steps,
            model.warning_steps,
            model.abort_at_step,
        ) == (steps, interval, (steps,), (steps,), steps)
    defaults = CountParameters(steps=3, interval_ms=0)
    assert (defaults.failed_steps, defaults.warning_steps, defaults.abort_at_step) == ((), (), None)
    invalid: list[dict[str, object]] = [
        {"steps": value} for value in (0, 10001, True, 1.5, "3", None)
    ]
    interval_changes: list[dict[str, object]] = [
        {"interval_ms": value} for value in (-1, 60001, True, 0.5, "0")
    ]
    invalid.extend(interval_changes)
    field_changes: list[dict[str, object]] = [
        {"failed_steps": [0]},
        {"failed_steps": [4]},
        {"failed_steps": [2, 2]},
        {"failed_steps": [True]},
        {"failed_steps": [1.0]},
        {"failed_steps": ["1"]},
        {"warning_steps": [0]},
        {"warning_steps": [4]},
        {"warning_steps": [2, 2]},
        {"warning_steps": [True]},
        {"warning_steps": [1.5]},
        {"abort_at_step": 0},
        {"abort_at_step": 4},
        {"abort_at_step": True},
        {"extra": "sensitive-marker"},
    ]
    invalid.extend(field_changes)
    for change in invalid:
        with pytest.raises(ValidationError) as caught:
            CountParameters.model_validate({"steps": 3, "interval_ms": 0} | change)
        assert "sensitive-marker" not in str(caught.value)


def test_count_success(tmp_path: Path) -> None:
    """验收6：三步零失败零警告，独立预期 succeeded；每步一个条目，最终3/3。"""
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}) as (work, dependencies, signals):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.summary is not None
        assert record == saved_record(dependencies.engine)
        assert (record.summary.state.value, record.summary.outcome, record.summary.aborted) == (
            "completed",
            "succeeded",
            False,
        )
        assert (
            record.summary.total_items,
            record.summary.failed_items,
            record.summary.warning_count,
        ) == (3, 0, 0)
        assert record.progress is not None and (
            record.progress.done,
            record.progress.total,
            record.progress.stage_count,
        ) == (3, 3, 1)
        assert sum(group.total for group in record.diagnostics) == 0
        assert record.artifacts == () and record.tool_exit_code is None


def test_count_warnings(tmp_path: Path) -> None:
    """验收6：三步中第二步警告，失败0警告1，独立预期 succeeded_with_warnings。"""
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0, "warning_steps": [2]}) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.summary is not None
        assert record == saved_record(dependencies.engine)
        assert (record.summary.state.value, record.summary.outcome, record.summary.aborted) == (
            "completed",
            "succeeded_with_warnings",
            False,
        )
        assert (
            record.summary.total_items,
            record.summary.failed_items,
            record.summary.warning_count,
        ) == (3, 0, 1)
        assert record.progress is not None and (
            record.progress.done,
            record.progress.total,
            record.progress.stage_count,
        ) == (3, 3, 1)
        assert sum(group.total for group in record.diagnostics) == 1
        assert record.artifacts == () and record.tool_exit_code is None


def test_count_partial(tmp_path: Path) -> None:
    """验收6：三步第二步失败且可同时警告，failed_items=1/3，独立预期 partially_succeeded。"""
    with execution_case(
        tmp_path, {"steps": 3, "interval_ms": 0, "warning_steps": [2], "failed_steps": [2]}
    ) as (work, dependencies, signals):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.summary is not None
        assert record == saved_record(dependencies.engine)
        assert (record.summary.state.value, record.summary.outcome, record.summary.aborted) == (
            "completed",
            "partially_succeeded",
            False,
        )
        assert (
            record.summary.total_items,
            record.summary.failed_items,
            record.summary.warning_count,
        ) == (3, 1, 1)
        assert record.progress is not None and (
            record.progress.done,
            record.progress.total,
            record.progress.stage_count,
        ) == (3, 3, 1)
        assert sum(group.total for group in record.diagnostics) == 2
        assert record.artifacts == () and record.tool_exit_code is None


def test_count_all_failed(tmp_path: Path) -> None:
    """验收6：三步全部失败，failed_items=total_items=3，独立预期 failed。"""
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0, "failed_steps": [1, 2, 3]}) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.summary is not None
        assert record == saved_record(dependencies.engine)
        assert (record.summary.state.value, record.summary.outcome, record.summary.aborted) == (
            "completed",
            "failed",
            False,
        )
        assert (
            record.summary.total_items,
            record.summary.failed_items,
            record.summary.warning_count,
        ) == (3, 3, 0)
        assert record.progress is not None and (
            record.progress.done,
            record.progress.total,
            record.progress.stage_count,
        ) == (3, 3, 1)
        assert sum(group.total for group in record.diagnostics) == 3
        assert record.artifacts == () and record.tool_exit_code is None


def test_count_aborted(tmp_path: Path) -> None:
    """验收6/6.11：第三步处理前整体中止，保留前两步计数，aborted=True结果failed，诊断含编号/步数/后果。"""
    with execution_case(tmp_path, {"steps": 4, "interval_ms": 0, "abort_at_step": 3}) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.summary is not None
        assert (record.summary.outcome, record.summary.aborted, record.summary.total_items) == (
            "failed",
            True,
            2,
        )
        diagnostic = record.diagnostics[-1].samples[0]
        assert any(item.key == "job_id" and item.value == "71" for item in diagnostic.objects)
        assert any(item.key == "step" and item.value == "3" for item in diagnostic.objects)
        assert diagnostic.actual and diagnostic.consequence and diagnostic.next_step


def _incompatible_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, missing: bool) -> None:
    """使用真实队列与worker公共循环，后一条正常作业必须完成，诊断不得复制旧参数原文。"""
    import time

    from jobs_loop_support import running_loop, wait_for
    from jobs_storage_support import NOW, job_database, job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs import policy
    from rdp.jobs.execution import ExecutorDependencies
    from rdp.jobs.records import find_job
    from rdp.jobs.types import JobClock, JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)
    with job_database(tmp_path) as (engine, paths):
        first = job_row(JobState.QUEUED)
        if missing:
            first.type_name = "removed_type"
        else:
            first.parameters = {"steps": "拒绝载荷标记", "interval_ms": 0}
        with session_scope(engine) as session:
            session.add_all([first, job_row(JobState.QUEUED, job_id=72)])
        dependencies = ExecutorDependencies(
            engine,
            production_registry(),
            paths,
            JobClock(lambda: NOW, time.monotonic),
            resources=resources_fixture(production_registry()),
            storage=None,
        )

        def done() -> bool:
            with session_scope(engine, read_only=True) as session:
                return find_job(session, 72).state is JobState.COMPLETED

        with running_loop(dependencies) as (_, _, results):
            wait_for(done)
        assert results[0].code == 0
        with session_scope(engine, read_only=True) as session:
            record = find_job(session, 71)
        assert record.state is JobState.COMPLETED and record.started_at is not None
        assert (
            record.summary is not None
            and record.summary.aborted
            and record.summary.outcome == "failed"
        )
        diagnostic = record.diagnostics[0].samples[0]
        assert any(
            item.key == "type" and item.value == first.type_name for item in diagnostic.objects
        )
        assert diagnostic.actual and diagnostic.consequence
        assert "拒绝载荷标记" not in diagnostic.model_dump_json()
