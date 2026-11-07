"""统计大小作业装配（领域层，M1-02、ADR0005/0006），不写数据、不拿导航写锁。

提交复用JobService及现有类型登记；只发布完整遍历结果，不将未完成统计写成零。
发布后保存自动大小同步计划并排队 nav_size_sync，统计本身仍不拿写锁、不写导航层。
"""

import logging
from dataclasses import dataclass
from pathlib import Path

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
)
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.datasets import _size_access, _sizing_index
from rdp.jobs.datasets._issues import input_error
from rdp.jobs.datasets._panel_issue import VALUE_PREVIEW_CHARS
from rdp.jobs.datasets._sizing_types import SizeDataset, SizeSource, SizeValue
from rdp.jobs.datasets._storage_paths import locate_path
from rdp.jobs.datasets.catalog import SIZING_NAME, SIZING_TYPE
from rdp.jobs.datasets.fingerprint import fingerprint_dataset
from rdp.jobs.datasets.rescan import RescanDependencies, RescanParameters
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.models import NavWritePlan
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.size_sync import plan_size_update, submit_size_sync
from rdp.jobs.registry import JobDefinition
from rdp.jobs.schedules import local_timezone
from rdp.jobs.types import JobProgress, RecoveryMode

logger = logging.getLogger(__name__)

# 两类作业具有相同范围契约，复用已批准校验，不复制编号规则。
SizingParameters = RescanParameters


def build_sizing_definition(
    dependencies: RescanDependencies | None,
    nav_dependencies: NavWriteDependencies | None = None,
) -> JobDefinition:
    """构造dataset_sizing类型，手动和系统提交使用同一参数校验与执行入口。

    Args:
        dependencies: worker的受管数据库、绝对导航根和只读检查器；Web登记传None。
        nav_dependencies: 自动同步的状态布局及队列依赖；None 只发布索引。

    Returns:
        默认并发1、无需GPU、RESTART恢复、无写入存储声明的作业定义。

    Raises:
        无；执行依赖在运行时验证，Web仅获得提交参数校验。

    Side Effects:
        只构造类型定义，不访问导航或存储，不提交作业。

    Time Semantics:
        入口启动登记时调用，统计结果的UTC时间在实际遍历完成后取得。
    """
    return JobDefinition(
        SIZING_TYPE,
        SIZING_NAME,
        SizingParameters,
        RecoveryMode.RESTART,
        _SizingExecutor(dependencies, nav_dependencies).execute,
        submission_role=Role.MEMBER,
    )


@dataclass(frozen=True)
class _SizingExecutor:
    """worker绑定执行能力。

    Attributes:
        dependencies: 只读扫描依赖；None只允许用于Web登记。
        nav_dependencies: 自动同步依赖；None 不提交写入。
    """

    dependencies: RescanDependencies | None
    nav_dependencies: NavWriteDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """读取索引范围、遍历链接目标并原子发布每个数据集的完整统计。"""
        deps = self.dependencies
        if (
            deps is None
            or deps.storage is None
            or not isinstance(context.parameters, SizingParameters)
        ):
            raise DefectError()
        with session_scope(deps.engine, read_only=True) as session:
            datasets = _sizing_index.snapshot(session, context.parameters.dataset_id, deps.nav_root)
        if context.parameters.dataset_id is not None and not datasets:
            raise input_error(context.parameters.dataset_id, "数据集尚未建立索引，请先重新扫描")
        plans: list[NavWritePlan] = []
        warnings = total_bytes = published = 0
        cache: dict[tuple[Path, tuple[SizeSource, ...]], SizeValue] = {}
        for done, dataset in enumerate(datasets, start=1):
            context.reporter.check_cancelled()
            started_s = context.clock.monotonic()
            try:
                _verify_navigation(dataset, deps, context)
                values = _collect(dataset, deps, context, cache)
                _verify_navigation(dataset, deps, context)
                counted = sum(
                    values[(entry.path, link.ordinal)].size_bytes
                    for entry in dataset.entries
                    if entry.canonical
                    for link in entry.links
                )
                plan = None
                if self.nav_dependencies is not None:
                    nav = self.nav_dependencies
                    zone = nav.timezone or local_timezone(Path("/etc/localtime"))
                    plan = plan_size_update(
                        nav,
                        dataset,
                        counted,
                        ensure_utc(context.clock.now()).astimezone(zone).date(),
                        context.reporter.check_cancelled,
                    )
                # 前像读取仍属于本次观察；只有索引提交成功才把计划交给自动写入。
                with session_scope(deps.engine) as session:
                    _sizing_index.publish(session, dataset, values, ensure_utc(context.clock.now()))
                if plan is not None:
                    plans.append(plan)
                total_bytes += counted
                published += 1
                logger.info(
                    "数据集大小统计完成",
                    extra={
                        "fields": {
                            "dataset_id": dataset.dataset_id,
                            "size_bytes": counted,
                            "elapsed_s": max(0.0, context.clock.monotonic() - started_s),
                        }
                    },
                )
            except OSError as error:
                warnings += 1
                context.reporter.diagnostic(
                    _skip(dataset.dataset_id, f"{type(error).__name__}: {error}")
                )
            context.reporter.report(
                JobProgress(
                    stage_index=1,
                    stage_count=1,
                    stage_name=f"统计大小：{total_bytes}字节，{published}数据集，{warnings}跳过",
                    done=done,
                    total=len(datasets),
                    unit="数据集",
                    total_items=done,
                    failed_items=0,
                    warning_count=warnings,
                )
            )

        if self.nav_dependencies is not None:
            submit_size_sync(context, self.nav_dependencies, plans)


def _collect(
    dataset: SizeDataset,
    deps: RescanDependencies,
    context: ExecutionContext,
    cache: dict[tuple[Path, tuple[SizeSource, ...]], SizeValue],
) -> dict[tuple[str, int], SizeValue]:
    """每个链接先核对挂载；离线或缺失使整个数据集保留旧统计，避免部分和冒充总和。"""
    if deps.storage is None:
        raise DefectError()
    values: dict[tuple[str, int], SizeValue] = {}
    for entry in dataset.entries:
        for link in entry.links:
            if link.target is None:
                raise FileNotFoundError(f"入口{entry.path}的链接序号{link.ordinal}不存在")
            target = locate_path(
                deps.nav_root / entry.path / link.target, tuple(root.path for root in deps.roots)
            )
            root = next((root for root in deps.roots if target.is_relative_to(root.path)), None)
            if root is None:
                raise OSError(f"链接目标不在登记根内：{target}")
            status = deps.storage.check(root.name, checkpoint=context.reporter.check_cancelled)
            if not status.online:
                raise OSError(f"存储根{root.name}离线：{status.reason}")
            cache_key = (target, link.sources)
            value = cache.get(cache_key)
            if value is None:
                value = _size_access.measure(target, deps.storage, context, link.sources)
                if value is None:
                    raise TimeoutError(f"存储访问停滞：{target}")
                cache[cache_key] = value
            values[(entry.path, link.ordinal)] = value
    return values


def _skip(dataset_id: str, actual: str) -> Diagnostic:
    """跳过只累计警告，不将部分大小写成零。"""
    return Diagnostic(
        level=DiagnosticLevel.WARNING,
        category=DiagnosticCategory.EXTERNAL,
        stage="统计大小",
        source="平台",
        objects=(DiagnosticObject(key="dataset_id", value=dataset_id),),
        rule="SIZING_SKIPPED",
        actual=actual[:VALUE_PREVIEW_CHARS],
        expected="链接目标在线且完整遍历完成",
        consequence="保留该数据集上次统计值和时间",
        next_step="恢复存储或重新扫描导航后再统计",
    )


def _verify_navigation(
    dataset: SizeDataset, deps: RescanDependencies, context: ExecutionContext
) -> None:
    """无锁比较L12快照；变化只跳过，不能把旧目标的统计套到新导航。"""
    current = fingerprint_dataset(
        deps.nav_root,
        dataset.dataset_id,
        known_entry_paths=tuple(entry.path for entry in dataset.entries),
        checkpoint=context.reporter.check_cancelled,
    )
    if not current.verifiable or current != dataset.fingerprint:
        raise OSError("导航状态变化或不可验证")
