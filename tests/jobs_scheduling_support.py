"""第8张测试的显式资源装配夹具；只改构造，不替换执行、数据库、状态转换或原有断言。

这些测试不调用新增资源方法，使用无卡、无每日规则的隔离依赖；09资源契约测试另验证真实资源行为。
"""

from typing import cast
from unittest.mock import Mock
from zoneinfo import ZoneInfo

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
    schedules = Mock(spec=ScheduleRegistry)
    schedules.definitions.return_value = ()
    types = tuple(
        TypeCapacity(item.type_name, item.display_name, item.concurrency, item.requires_gpu)
        for item in registry.definitions()
    )
    return SchedulingCatalog(
        SchedulingSettings((), types), cast(ScheduleRegistry, schedules), ZoneInfo("UTC")
    )


def scheduling_fixture(registry: JobRegistry) -> WorkerScheduling:
    """无卡配置显式给nvidia_smi=None，清除保留期取正常30天，不默认发现本机工具。"""
    return WorkerScheduling(catalog_fixture(registry), None, 30)


def resources_fixture(registry: JobRegistry) -> WorkerResources:
    """提供独立的类型资源对象替身，不复用模块单例，也不改变旧作业的执行回调。"""
    return WorkerResources(
        scheduling_fixture(registry),
        cast(ResourcePool, Mock(spec=ResourcePool)),
        cast(NavigationWriter, Mock(spec=NavigationWriter)),
    )


def claim_fixture(record: JobRecord) -> ResourceClaim:
    """为已领取的无卡旧测试作业显式构造本次凭据，卡号取记录而非默认猜测。"""
    return ResourceClaim(record.job_id, record.type_name, record.gpu_index)
