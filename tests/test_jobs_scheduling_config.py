"""09 作业资源配置的公开边界测试；配置文件只使用临时目录。"""

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from rdp.infra.config import JobsConfig, PlatformConfig, load_config
from rdp.infra.diagnostics import DefectError, InputError
from rdp.infra.state import state_paths
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.scheduling import resolve_scheduling


def test_defaults(tmp_path: Path) -> None:
    """K1/验收1：无 jobs 配置时 gpus=(0,1)、类型默认并发1，且配置来源仍可追踪。"""
    loaded = load_config(environ={}, home=tmp_path)
    assert loaded.config.jobs.gpus == (0, 1)
    assert loaded.config.jobs.concurrency == {}
    assert loaded.source == tmp_path / ".config/rdp/config.toml"
    assert loaded.used_defaults is True
    definition = production_registry().lookup("example_count")
    assert definition is not None and definition.concurrency == 1
    assert not tuple(tmp_path.iterdir())


def test_empty_gpus(tmp_path: Path) -> None:
    """K1：显式空 GPU 列表合法，表示不用 GPU，不回退默认两张卡。"""
    source = tmp_path / "config.toml"
    source.write_text("[jobs]\ngpus = []\n", encoding="utf-8")
    loaded = load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    assert loaded.config.jobs.gpus == ()
    assert loaded.source == source and loaded.used_defaults is False


def test_gpu_validation(tmp_path: Path) -> None:
    """契约：GPU 拒绝 bool、负数、超上界、字符串、重复及超过64项列表，未知配置项拒绝。"""
    source = tmp_path / "config.toml"
    invalid = (
        "[0, 0]",
        "[true]",
        "[-1]",
        "[65536]",
        '["0"]',
        "[0.5]",
        "[" + ",".join(map(str, range(65))) + "]",
    )
    for value in invalid:
        source.write_text(f"[jobs]\ngpus = {value}\n", encoding="utf-8")
        with pytest.raises(ValueError) as caught:
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
        assert str(source) in str(caught.value) and "jobs.gpus" in str(caught.value)
    source.write_text("[jobs]\ngpus = [65535, 0]\n", encoding="utf-8")
    assert load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path).config.jobs.gpus == (
        65535,
        0,
    )
    source.write_text("[jobs]\nunknown = true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="jobs.unknown"):
        load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)


def test_concurrency_bounds(tmp_path: Path) -> None:
    """验收1：并发接受1和具名最大32，拒绝0、33、bool、浮点及字符串。"""
    source = tmp_path / "config.toml"
    for value in ("1", "32"):
        source.write_text(f"[jobs.concurrency]\nexample_count = {value}\n", encoding="utf-8")
        assert load_config(
            environ={"RDP_CONFIG": str(source)}, home=tmp_path
        ).config.jobs.concurrency == {"example_count": int(value)}
    for value in ("0", "33", "true", "1.5", '"2"'):
        source.write_text(f"[jobs.concurrency]\nexample_count = {value}\n", encoding="utf-8")
        with pytest.raises(ValueError, match="jobs.concurrency.example_count"):
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)
    for key in ("Upper", "bad-key", "x" * 65, "", "a\nb"):
        import json

        source.write_text(f"[jobs.concurrency]\n{json.dumps(key)} = 1\n", encoding="utf-8")
        with pytest.raises(ValueError, match="jobs.concurrency"):
            load_config(environ={"RDP_CONFIG": str(source)}, home=tmp_path)


def test_unknown_type() -> None:
    """契约：jobs.concurrency 的未登记键在 Web/worker 启动均拒绝，诊断指出配置键。"""
    config = JobsConfig.model_validate({"concurrency": {"unknown_type": 2}})
    with pytest.raises(InputError) as caught:
        resolve_scheduling(config, production_registry())
    diagnostic = caught.value.diagnostics[0]
    assert any(item.value == "jobs.concurrency.unknown_type" for item in diagnostic.objects)
    assert diagnostic.category.value == "input"
    assert diagnostic.actual and diagnostic.consequence and diagnostic.next_step


def test_invalid_definition() -> None:
    """契约：JobRegistry 拒绝非法声明上限和非bool requires_gpu，不增加登记项。"""
    original = production_registry().lookup("example_count")
    assert original is not None
    for value in (True, 0, 33, 1.5, "2"):
        registry = JobRegistry()
        with pytest.raises(DefectError):
            registry.register(replace(original, concurrency=cast(int, value)))
        assert registry.definitions() == ()
    for value in (1, None, "yes"):
        registry = JobRegistry()
        with pytest.raises(DefectError):
            registry.register(replace(original, requires_gpu=cast(bool, value)))
        assert registry.definitions() == ()


def test_resolve_sorted() -> None:
    """契约：覆盖优先于声明值，结果按类型/卡号排序且不因调用者随后修改配置而改变。"""
    base = production_registry().lookup("example_count")
    assert base is not None
    registry = JobRegistry()
    registry.register(
        replace(base, type_name="z_type", display_name="后类", concurrency=4, requires_gpu=True)
    )
    registry.register(replace(base, type_name="a_type", display_name="前类", concurrency=3))
    config = JobsConfig.model_validate({"gpus": [9, 2], "concurrency": {"z_type": 2}})
    result = resolve_scheduling(config, registry)
    assert result.gpus == (2, 9)
    assert [(item.type_name, item.concurrency, item.requires_gpu) for item in result.types] == [
        ("a_type", 3, False),
        ("z_type", 2, True),
    ]
    config.concurrency["z_type"] = 7
    assert result.types[1].concurrency == 2
    assert resolve_scheduling(JobsConfig.model_validate({"gpus": []}), JobRegistry()).gpus == ()
    for broken_config, broken_registry in ((None, registry), (config, None)):
        with pytest.raises(DefectError):
            resolve_scheduling(cast(JobsConfig, broken_config), cast(JobRegistry, broken_registry))


def test_state_path(tmp_path: Path) -> None:
    """契约：navigation_example 严格位于临时 state root，取路径不创建文件。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    assert paths.navigation_example == tmp_path / "state/navigation-example.jsonl"
    assert paths.navigation_example.is_absolute()
    assert not tuple(tmp_path.iterdir())


def test_production_types() -> None:
    """契约：生产登记十五种类型，两个清除为restart、三个示例为interrupt，写导航层的 nav_write_apply 为interrupt，只有example_gpu需卡。"""
    definitions = production_registry().definitions()
    assert [
        (
            item.type_name,
            item.display_name,
            item.recovery_mode.value,
            item.concurrency,
            item.requires_gpu,
        )
        for item in definitions
    ] == [
        ("dataset_rescan", "重新扫描数据集", "restart", 1, False),
        ("dataset_sizing", "统计数据集大小", "restart", 1, False),
        ("download", "下载", "resume", 1, False),
        ("example_count", "示例：数数", "interrupt", 1, False),
        ("example_gpu", "示例：占用 GPU", "interrupt", 1, True),
        ("example_navigation", "示例：写锁", "interrupt", 1, False),
        ("nav_create_dataset_preview", "预览新增数据集", "restart", 1, False),
        ("nav_create_link_preview", "预览建链", "restart", 1, False),
        ("nav_data_origin_preview", "预览改数据来源", "restart", 1, False),
        ("nav_fields_preview", "预览编辑字段", "restart", 1, False),
        ("nav_repoint_preview", "预览改指向", "restart", 1, False),
        ("nav_revert_preview", "预览撤回", "restart", 1, False),
        ("nav_write_apply", "写导航层", "interrupt", 1, False),
        ("purge_audit_logs", "清除过期日志", "restart", 1, False),
        ("purge_errors", "清除过期报错", "restart", 1, False),
    ]
    assert all(callable(item.execute) for item in definitions)
    assert {item.type_name for item in definitions if item.writes_navigation} == {"nav_write_apply"}


def test_required_dependencies_have_no_defaults() -> None:
    """阻塞3：run_worker/configure_jobs/claim_job与执行依赖/凭据构造缺必填关键字时TypeError；允许无值的字段也须显式None。"""
    import inspect

    from rdp.api.jobs import JobApiContext, configure_jobs
    from rdp.jobs.execution import ExecutionContext, ExecutionWork, ExecutorDependencies
    from rdp.jobs.records import claim_job
    from rdp.ops.worker import run_worker

    for target, names in (
        (run_worker, ("scheduling",)),
        (configure_jobs, ("scheduling",)),
        (claim_job, ("gpu_index",)),
        (ExecutorDependencies, ("resources",)),
        (ExecutionWork, ("claim",)),
        (JobApiContext, ("scheduling",)),
        (
            ExecutionContext,
            (
                "_navigation",
                "gpu_index",
                "maintenance",
                "gpu_example_command",
                "navigation_example_path",
            ),
        ),
    ):
        signature = inspect.signature(target)
        for name in names:
            parameter = signature.parameters[name]
            assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
            assert parameter.default is inspect.Parameter.empty
        with pytest.raises(TypeError):
            signature.bind()
