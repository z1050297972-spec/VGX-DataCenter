"""运维重建入口（M1-06）；复用配置、worker锁与两段扫描，不启动服务或统计大小。"""

import logging
from datetime import datetime
from typing import TextIO

from sqlalchemy.orm import Session

from rdp.audit.records import append_operation
from rdp.audit.types import (
    OPS_AUDIT_CONTEXT,
    AuditValues,
    ObjectRef,
    OperationDetails,
    OperationEvent,
    OperationResult,
    OperationType,
)
from rdp.infra.actors import OPS_ACTOR
from rdp.infra.config import PlatformConfig, load_config
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.db.migration import check_database_version
from rdp.infra.diagnostics import ConflictError, DiagnosticCategory, ExternalError, InputError
from rdp.infra.state import StatePaths, state_paths
from rdp.infra.storage import MountInspector, StorageAccessChecker, read_storage_root
from rdp.jobs._clock import ClockReader
from rdp.jobs.datasets.index import replace_index
from rdp.jobs.datasets.rebuild import clear_index, plan_rebuild
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.worker import worker_lock
from rdp.ops.runtime import RuntimeInputs
from rdp.ops.status import check_worker_stopped

logger = logging.getLogger(__name__)


def rebuild_index(inputs: RuntimeInputs, *, stdout: TextIO) -> int:
    """在 worker 停止时同步重建数据集索引。

    Args:
        inputs: 显式配置、临时或部署HOME及UTC/单调时钟依赖。
        stdout: 操作摘要输出流，不接受业务参数。

    Returns:
        成功为0；拒绝或执行失败传播到命令边界。

    Raises:
        ConflictError: worker正在运行或事务锁竞争；运行冲突提示改到网页上提交。
        InputError: 数据库版本、索引或导航输入不合格；不自动迁移。
        ExternalError: 锁、导航、存储、数据库或操作日志I/O失败。
        DefectError: 注入时钟、锁路径或扫描阶段依赖非法。
        ValueError: 最终配置不合法。
        OSError: 配置文件读取或终端输出失败；已提交结果不因输出失败回滚。
        KeyboardInterrupt: 操作者取消；未提交的发布事务回滚，旧索引保留，命令边界返回130。

    Side Effects:
        取得worker锁后用空基线完成两段扫描；发布时清空八张索引表，与新索引及成功日志同事务提交。
        发布或成功审计失败回滚，旧索引及统计值保持原样，再补记失败操作。
        扫描阶段失败按删掉重建的约定清空索引并补记失败日志；审计补记失败保留原异常并报告日志缺口。
        不创建作业或统计大小，不修改导航、存储根、账号和布局偏好；拒绝持锁时不写数据库。
        所有路径先关闭引擎再释放实例锁；配置只加载一次，避免执行中切换到另一状态目录。

    Time Semantics:
        worker锁非阻塞取得，持续覆盖清空、采集、复核、发布及摘要输出；没有恢复或调度循环。
        UTC用于扫描和审计，单调秒用于耗时；存储检查复用每根access_timeout_s，数据库沿用5秒预算。
    """
    config = load_config(environ=inputs.environ, home=inputs.home).config
    paths = state_paths(config, ())
    available = check_worker_stopped(paths.worker_lock)
    if not available.allowed:
        raise ConflictError(
            tuple(
                item.model_copy(update={"next_step": "请改到网页上提交重新扫描作业"})
                for item in available.diagnostics
            )
        )
    # 预检只负责拒绝说明；必须真正取得锁，封闭预检后worker启动的竞争窗口。
    try:
        lock = worker_lock(paths)
    except ConflictError as error:
        raise ConflictError(
            tuple(
                item.model_copy(update={"next_step": "请改到网页上提交重新扫描作业"})
                for item in error.diagnostics
            )
        ) from error
    try:
        return _rebuild_locked(inputs, config, paths, stdout=stdout)
    finally:
        # 存储超时线程只读并丢弃迟到结果；同步发布完成后没有持库或导航写线程。
        lock.finish(())


def _rebuild_locked(
    inputs: RuntimeInputs, config: PlatformConfig, paths: StatePaths, *, stdout: TextIO
) -> int:
    """单实例锁内装配并同步发布；所有失败都先关闭引擎再交外层释放锁。"""
    ClockReader(inputs.clock).read()
    check_database_version(paths.database)
    engine = create_database_engine(paths.database)
    try:
        inspector = MountInspector(
            config.storage_roots,
            inputs.mounts.read_mountinfo,
            inputs.mounts.resolve_uuid_device,
            inputs.clock.now,
        )
        dependencies = RescanDependencies(
            engine,
            config.nav_root,
            config.storage_roots,
            StorageAccessChecker(inspector, config.storage, read_storage_root),
        )
        started = inputs.clock.monotonic()
        scanned = False
        try:
            # 先算空基线计划，发布事务内才清空；数据库故障能真正回滚至旧索引。
            plan = plan_rebuild(dependencies, clock=inputs.clock)
            scanned = True
            with session_scope(engine) as session:
                clear_index(session)
                result = replace_index(session, plan)
                _record(session, inputs.clock.now(), None)
        except Exception as error:
            if not scanned:
                # 按工单“删掉重建”的扫描失败语义清空；不得把旧索引冒充本次扫描结果。
                with session_scope(engine) as session:
                    clear_index(session)
                stdout.write("索引现在是空的，修好原因后重跑 rdp rebuild-index。\n")
            category = (
                DiagnosticCategory.INPUT
                if isinstance(error, InputError)
                else DiagnosticCategory.CONFLICT
                if isinstance(error, ConflictError)
                else DiagnosticCategory.EXTERNAL
                if isinstance(error, (ExternalError, OSError))
                else DiagnosticCategory.DEFECT
            )
            try:
                with session_scope(engine) as session:
                    _record(session, inputs.clock.now(), category)
            except Exception:
                # 原失败不能被日志补记失败覆盖；明确报告审计缺口，不能伪称已记录。
                logger.error("重建索引的失败操作日志补记失败", exc_info=True)
                error.add_note("失败操作日志补记失败，请查看运行日志")
            raise
        stdout.write(
            f"重建索引完成：数据集 {result.dataset_count}，入口 {result.entry_count}，发现 {result.finding_count}，跳过 {result.skipped_dataset_count}，失败入口 {result.failed_entry_count}，警告 {result.warning_count}；耗时 {max(0.0, inputs.clock.monotonic() - started):.3f} 秒，第一段持锁 {plan.navigation.lock_held_s:.3f} 秒\n"
        )
        stdout.write("统计大小未重建：留给下一次每晚作业，或在页面上手动提交。\n")
        return 0
    finally:
        engine.dispose()


def _record(session: Session, now: datetime, failure: DiagnosticCategory | None) -> None:
    """用同一个明确操作码记录结果；成功跟索引发布同事务，失败独立补记。"""
    append_operation(
        session,
        OperationEvent(
            occurred_at=now,
            actor=OPS_ACTOR,
            operation=OperationType.REBUILD_INDEX,
            target=ObjectRef("dataset_index", "all", "数据集索引"),
            result=OperationResult.SUCCESS if failure is None else OperationResult.FAILURE,
            failure_category=failure,
            context=OPS_AUDIT_CONTEXT,
            details=OperationDetails(before=AuditValues(), after=AuditValues()),
        ),
    )
