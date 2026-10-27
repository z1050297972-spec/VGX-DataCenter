"""第8张测试的显式资源装配夹具；只改构造，不替换执行、数据库、状态转换或原有断言。

无卡、无每日规则的真实资源对象用于旧执行测试；模拟重启时明确重建空资源池。
"""

from dataclasses import replace
from zoneinfo import ZoneInfo

from rdp.jobs.execution import ExecutorDependencies
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.registry import JobRegistry
from rdp.jobs.resources import ResourcePool
from rdp.jobs.schedules import ScheduleRegistry
from rdp.jobs.scheduling import WorkerResources, WorkerScheduling
from rdp.jobs.scheduling_types import (
    ResourceClaim,
    SchedulingCatalog,
    SchedulingSettings,
    TypeCapacity,
)
from rdp.jobs.types import JobRecord


def catalog_fixture(registry: JobRegistry) -> SchedulingCatalog:
    """显式构造与本测试登记相符的无卡、空每日规则及UTC时区，不读真实配置或硬件。"""
    schedules = ScheduleRegistry((), registry)
    types = tuple(
        TypeCapacity(item.type_name, item.display_name, item.concurrency, item.requires_gpu)
        for item in registry.definitions()
    )
    return SchedulingCatalog(SchedulingSettings((), types), schedules, ZoneInfo("UTC"))


def scheduling_fixture(registry: JobRegistry) -> WorkerScheduling:
    """无卡配置显式给nvidia_smi=None，清除保留期取正常30天，不默认发现本机工具。"""
    return WorkerScheduling(catalog_fixture(registry), None, 30)


def resources_fixture(registry: JobRegistry) -> WorkerResources:
    """提供独立的真实类型资源对象，不复用模块单例，也不改变旧作业的执行回调。"""
    configuration = scheduling_fixture(registry)
    return WorkerResources(
        configuration,
        ResourcePool(configuration.catalog.settings, available_gpus=()),
        NavigationWriter(),
    )


def claim_fixture(record: JobRecord, dependencies: ExecutorDependencies) -> ResourceClaim:
    """为直接执行测试领取真实无卡凭据，执行器结束时可核对并归还。"""
    assert dependencies.resources is not None
    claim = dependencies.resources.pool.reserve(record.job_id, record.type_name).claim
    assert claim is not None
    return claim


def fresh_dependencies(dependencies: ExecutorDependencies) -> ExecutorDependencies:
    """模拟worker重启：沿用数据库/时钟，重建空内存资源，不能复用上个实例的凭据。"""
    return replace(dependencies, resources=resources_fixture(dependencies.registry))
