"""同步扫描适配（领域层，M1-06）；复用两段采集、指纹和发布计划，不建立第二套扫描规则。

运维进程已独占worker锁，无并发导航写者；不伪造作业编号、队列提交人或作业进度。
标准库时钟与现有扫描实现足够，不引入依赖；具体事务及审计由入口组合。
"""

from sqlalchemy import delete
from sqlalchemy.orm import Session

from rdp.infra.timeutil import ensure_utc
from rdp.jobs.datasets import _fingerprints, _stage
from rdp.jobs.datasets.index import plan_index_replacement
from rdp.jobs.datasets.models import DatasetRow, DatasetScanRow, EntryRow, FindingRow
from rdp.jobs.datasets.rescan import RescanDependencies, scan_storage
from rdp.jobs.datasets.scan_types import IndexReplacement, NavigationScan
from rdp.jobs.types import JobClock


def clear_index(session: Session) -> None:
    """清空可重建的数据集索引，保留永久业务记录及账号偏好。

    Args:
        session: 已进入写事务的受管会话，调用方持有worker单实例锁。

    Returns:
        无；删除尚未提交，由调用方决定事务结果。

    Raises:
        SQLAlchemyError: 删除或外键约束失败，由外层session_scope转换异常并回滚。

    Side Effects:
        删除发现、全部入口（含未知身份入口）、数据集和扫描代次；文档、链接、数据块和根状态级联删除。
        不删除作业、账号、操作日志或布局偏好，不访问导航层。

    Time Semantics:
        单个写事务，先删除引用再删除代次；与新索引及成功审计一同提交，或用于扫描失败后的清空。
    """
    # 未知身份入口不属于任何DatasetRow，不能只依赖数据集的级联删除。
    for model in (FindingRow, EntryRow, DatasetRow, DatasetScanRow):
        session.execute(delete(model))


def plan_rebuild(dependencies: RescanDependencies, *, clock: JobClock) -> IndexReplacement:
    """在独占运维窗口采集两段全量扫描并生成复核后的发布计划。

    Args:
        dependencies: 受管引擎、绝对导航根、登记根和必备存储检查器。
        clock: UTC墙钟和单调秒时钟，不使用文件mtime作为扫描时刻。

    Returns:
        两段扫描及末次指纹核对形成的完整计划，job_id为None，基线恒为空，不复用旧索引或大小。

    Raises:
        InputError: 导航输入损坏、超过现有扫描预算。
        ExternalError: 导航枚举或存储访问失败。
        DefectError: 缺少存储检查器、时钟或扫描阶段身份无效。

    Side Effects:
        只读导航及登记存储根；不读取旧索引，不创建作业、修改文件或提交索引。

    Time Semantics:
        调用方必须持续持有worker单实例锁直至发布结束；本进程同步执行，没有并发写者。
        第一段用单调秒测时；第二段逐根沿用access_timeout_s，无重试。
        返回后应立即发布，手工改文件只能用末次指纹尽力发现。
    """
    from rdp.infra.diagnostics import DefectError

    if dependencies.storage is None:
        raise DefectError()
    started_at = ensure_utc(clock.now())
    started = clock.monotonic()
    # 重建不复用旧索引；空基线使损坏指纹不参与扫描，旧行留到发布事务才清空。
    datasets, findings = _stage.observe(dependencies.nav_root, None, (), _checkpoint)
    elapsed_s = max(0.0, clock.monotonic() - started)
    navigation = NavigationScan(
        None,
        dependencies.roots,
        (),
        datasets,
        findings,
        started_at,
        ensure_utc(clock.now()),
        elapsed_s,
        elapsed_s,
    )
    storage = scan_storage(navigation, dependencies, checkpoint=_checkpoint)
    observed = _fingerprints.collect(dependencies.nav_root, _checkpoint)
    current = tuple(
        _fingerprints.select(
            dependencies.nav_root,
            item.dataset_id,
            tuple(entry.path for entry in item.fingerprint.entries),
            observed,
            _checkpoint,
        )
        for item in navigation.datasets
    )
    return plan_index_replacement(navigation, storage, current, committed_at=clock.now())


def _checkpoint() -> None:
    """同步运维没有作业取消请求，Ctrl-C仍由Python原样传播到入口。"""
