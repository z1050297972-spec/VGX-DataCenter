"""重新扫描作业装配（领域层，M1-01、ADR 0005/0006），不实现自己的锁、队列或恢复器。

类型执行器持有入口注入的数据库和导航配置；Web只登记相同参数模型，不获得文件访问能力。
生产登记通过build_rescan_definition显式加入JobRegistry，恢复、取消、结果均由M0框架收口。
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs import _storage
from rdp.jobs.datasets import _fingerprints, _stage, _storage_scan
from rdp.jobs.datasets.catalog import RESCAN_NAME, RESCAN_TYPE
from rdp.jobs.datasets.index import plan_index_replacement, read_index_baseline, replace_index
from rdp.jobs.datasets.scan_types import NavigationScan, ScanPublication, StorageScan, StorageStage
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import ExecutionMode, JobProgress, RecoveryMode

logger = logging.getLogger(__name__)


class RescanParameters(BaseModel):
    """扫描范围参数，不能指定导航路径、存储根或提交人。

    Attributes:
        model_config: 不可变，拒绝多余字段，不回显不可信输入。
        dataset_id: None为全量；否则非空、无路径分隔符的永久编号；上限256码点。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    dataset_id: str | None = Field(
        default=None, strict=True, min_length=1, max_length=256, pattern=r"^[^/\\\s\x00]+$"
    )


@dataclass(frozen=True)
class RescanDependencies:
    """worker专用的扫描依赖，不通过作业参数注入基础设施。

    Attributes:
        engine: 已迁移且受管的SQLite引擎，每次调用独立Session。
        nav_root: 配置给出的绝对普通目录，不使用全局默认路径。
        roots: 已校验存储根配置元组，可空，只保存登记事实。
        storage: worker注入只读超时访问检查器；None表示仅运行第一段，第二段明确NOT_RUN。
    """

    engine: Engine
    nav_root: Path
    roots: tuple[StorageRootConfig, ...]
    storage: StorageAccessChecker | None


@dataclass(frozen=True)
class RescanExecutor:
    """绑定扫描能力的作业执行对象，实例由worker装配，不是可变单例。

    Attributes:
        dependencies: worker专用依赖；Web类型登记传None，执行时缺依赖属于程序缺陷。
    """

    dependencies: RescanDependencies | None

    def execute(self, context: ExecutionContext) -> None:
        """执行两段扫描并发布索引，交框架计算最终作业结果。

        Args:
            context: RescanParameters上下文，mode只允许FRESH/RESTART，导航锁由worker共享。

        Returns:
            无；摘要含数据集数、入口数、跳过数、面板发现数及第二段执行状态。
            条目单位为入口；必需文档不可用造成不完整投影时该入口计一次失败。
            其他面板①②组发现不计失败；跳过更新或存储离线才累计作业warning_count。

        Raises:
            JobCancelledError: 阶段间或入口检查点收到取消，持锁段延后；提交前取消保留旧索引。
            WorkerStoppingError: worker停止，保留running供框架按RESTART恢复。
            InputError: 参数不合法、单数据集在导航和基线都不存在，或读取预算超过上限。
            ConflictError: 导航锁超过框架上限或索引写事务竞争。
            ExternalError: 整个导航无法枚举、索引事务或进度/作业日志I/O失败。
            DefectError: Web缺执行依赖、参数模型/恢复模式错误、非法时钟或阶段交接错误。

        Side Effects:
            调用scan_navigation→释放写锁→scan_storage→publish_scan；不直接赋作业结果。
            三阶段进度由reporter最多每秒落盘，发布成功后才累计已提交条目；发现与失败分别计数。
            失败/取消不写导航，事务失败保留旧索引；提交后取消不回滚已成功发布的索引。
            RESTART从头采集，不沿用上次快照或累计进度；恢复次数仍遵循M0框架上限。

        Time Semantics:
            第一段和最终复核/提交分别持锁，第二段始终无锁；所有锁等待复用300秒框架预算。
            阶段间检查取消；持锁区延后取消/停止且每次文件读块触发检查点，耗时用context.clock。
        """
        if (
            self.dependencies is None
            or not isinstance(context.parameters, RescanParameters)
            or context.mode not in {ExecutionMode.FRESH, ExecutionMode.RESTART}
        ):
            raise DefectError()
        context.reporter.check_cancelled()
        navigation = scan_navigation(context, self.dependencies)
        context.reporter.report(
            JobProgress(
                stage_index=1,
                stage_count=3,
                stage_name="读取导航层",
                done=1,
                total=1,
                unit="阶段",
                total_items=0,
                failed_items=0,
                warning_count=0,
            )
        )
        context.reporter.check_cancelled()
        storage = scan_storage(
            navigation, self.dependencies, checkpoint=context.reporter.check_cancelled
        )
        context.reporter.report(
            JobProgress(
                stage_index=2,
                stage_count=3,
                stage_name="检查存储根"
                if storage.stage is StorageStage.COMPLETED
                else "存储检查未执行",
                done=1,
                total=1,
                unit="阶段",
                total_items=0,
                failed_items=0,
                warning_count=0,
            )
        )
        publication = publish_scan(context, self.dependencies, navigation, storage)
        context.reporter.report(
            JobProgress(
                stage_index=3,
                stage_count=3,
                stage_name=f"发布索引：{publication.dataset_count}数据集、{publication.finding_count}发现、{publication.skipped_dataset_count}跳过",
                done=publication.entry_count,
                total=publication.entry_count,
                unit="入口",
                total_items=publication.entry_count,
                failed_items=publication.failed_entry_count,
                warning_count=publication.warning_count,
            )
        )
        logger.info(
            "重新扫描发布完成",
            extra={
                "fields": {
                    "dataset_count": publication.dataset_count,
                    "entry_count": publication.entry_count,
                    "finding_count": publication.finding_count,
                    "lock_held_s": navigation.lock_held_s,
                }
            },
        )
        context.reporter.check_cancelled()


def build_rescan_definition(dependencies: RescanDependencies | None) -> JobDefinition:
    """构造重新扫描的显式作业类型定义，供两个入口加入现有登记表。

    Args:
        dependencies: worker传完整依赖；Web传None，只能校验提交参数，不能执行扫描。

    Returns:
        type_name=RESCAN_TYPE、display_name=RESCAN_NAME、RescanParameters、RecoveryMode.RESTART，
        execute绑定RescanExecutor.execute；默认并发1，无GPU、storage声明为空。
        空storage避免作业开跑前因离线根整体失败，第二段按数据集降级检查。

    Raises:
        DefectError: 注入引擎不受管、nav_root非绝对路径或根配置名重复。

    Side Effects:
        只构造定义，不执行、不注册全局单例、不读配置文件或存储根。

    Time Semantics:
        Web/worker各在启动登记期构造一次；参数及恢复方式不受提交人覆盖。
    """
    if dependencies is not None:
        if (
            not dependencies.engine.get_execution_options().get("rdp_managed")
            or not dependencies.nav_root.is_absolute()
        ):
            raise DefectError()
        if len({root.name for root in dependencies.roots}) != len(dependencies.roots):
            raise DefectError()
    return JobDefinition(
        RESCAN_TYPE,
        RESCAN_NAME,
        RescanParameters,
        RecoveryMode.RESTART,
        RescanExecutor(dependencies).execute,
    )


def scan_navigation(context: ExecutionContext, dependencies: RescanDependencies) -> NavigationScan:
    """持共享导航锁读取全部指定入口及基线，并在同保护段采集指纹。

    Args:
        context: 已校验重新扫描参数的执行上下文，包含控制信号和注入时钟。
        dependencies: 本worker的受管引擎、导航根和配置根；不使用storage访问能力。

    Returns:
        完整NavigationScan，归组依据dataset_id，未知身份单独保留位置。
        单数据集仍发现全部视图入口，不能只扫索引里旧路径；坏文件不会丢掉目录占位。
        投影读取的原字节摘要必须与同段指纹一致；期间手工修改导致不一致时标为不可验证，
        不能把旧投影和新指纹配对发布。复核只重读已捕获的导航输入，不跟随目标。
        第一段JSON总读取预算MAX_SCAN_BYTES、入口MAX_SCAN_ENTRIES；不返回截短的全量结果。

    Raises:
        InputError: 范围不存在、路径或预算非法，不把局部快照当全量交给发布。
        ExternalError: 导航根/视图枚举失败；单份文件故障则归读取发现，不抛整批失败。
        ConflictError: context.write_navigation等待超过框架上限。
        JobCancelledError: 等锁或进入保护区前取消。
        WorkerStoppingError: 等锁或进入保护区前停止。
        DefectError: 时钟、依赖或参数类型无效。

    Side Effects:
        只读索引基线和导航；通过context.write_navigation执行保护回调，不直接持有新锁。
        产生①②组及缺来源/缺记录值发现，日志记录范围、入口数和持锁耗时；不写索引。

    Time Semantics:
        先取锁再读基线及目录，读完指纹后放锁；UTC记录时刻，单调秒记录耗时。
        不在本阶段探测存储、等待任务或开放第二段并行回调。
    """
    parameters = context.parameters
    if not isinstance(parameters, RescanParameters):
        raise DefectError()
    started_at = _storage.moment(context.clock.now())
    started = context.clock.monotonic()

    def read() -> NavigationScan:
        locked = context.clock.monotonic()
        with session_scope(dependencies.engine, read_only=True) as session:
            baseline = read_index_baseline(
                session, parameters.dataset_id, nav_root=dependencies.nav_root
            )
        datasets, findings = _stage.observe(
            dependencies.nav_root, parameters.dataset_id, baseline, context.reporter.check_cancelled
        )
        ended = context.clock.monotonic()
        return NavigationScan(
            parameters.dataset_id,
            dependencies.roots,
            baseline,
            datasets,
            findings,
            started_at,
            _storage.moment(context.clock.now()),
            max(0.0, ended - started),
            max(0.0, ended - locked),
            job_id=context.job_id,
        )

    return context.write_navigation(lambda: None, read)


def scan_storage(
    navigation: NavigationScan,
    dependencies: RescanDependencies,
    *,
    checkpoint: Callable[[], None],
) -> StorageScan:
    """在导航锁外检查存储根、链接、数据块与元信息，返回③④组发现。

    Args:
        navigation: 第一段完整快照，第二段只检查其中路径，不递归统计大小。
        dependencies: 显式扫描依赖；storage为None时保留仅导航扫描模式并返回NOT_RUN。
        checkpoint: 必填控制检查点，在调用线程进入及等待各根期间调用，控制异常原样传播。

    Returns:
        有检查器时返回COMPLETED，含每根状态、链接/数据块观察及按归属聚合的③④组发现。
        离线或超时的根只报顶部问题，链接和数据块标为离线；warning_count为离线根数。
        没有检查器返回NOT_RUN和空集合、零警告；不冒充在线，不修改已有大小。

    Raises:
        JobCancelledError: 检查点收到取消。
        WorkerStoppingError: 检查点收到停止。
        ExternalError: 挂载表、路径元数据或目录枚举I/O失败；元信息不可读则字段归未知。
        DefectError: 第一段快照、检查器根配置或时钟非法。

    Side Effects:
        只读挂载表、根内路径及meta/info.json，不获取导航锁、不修改导航或存储根，不提交数据库。
        每根使用M0超时线程；超时丢弃该根部分结果，迟到线程不发布结果。

    Time Semantics:
        第一段放锁后调用；每批根内读取受access_timeout_s预算限制，无重试。
        跨根软链接在目标根重新核对身份并使用独立预算，解析最多40跳。
        UTC检查时刻来自检查器时钟，耗时用单调秒；超时不能强行结束内核读取（M0限制）。
    """
    checkpoint()
    if not isinstance(cast(object, navigation), NavigationScan) or not isinstance(
        cast(object, dependencies), RescanDependencies
    ):
        raise DefectError()
    if dependencies.storage is None:
        return StorageScan(StorageStage.NOT_RUN, (), (), (), (), 0)
    if (
        navigation.registered_roots != dependencies.roots
        or dependencies.storage.mounts.roots != dependencies.roots
    ):
        raise DefectError()
    started = time.monotonic()
    result = _storage_scan.scan(navigation, dependencies.storage, checkpoint)
    logger.info(
        "存储扫描完成",
        extra={
            "fields": {
                "elapsed_s": time.monotonic() - started,
                "offline_roots": result.warning_count,
                "link_count": len(result.links),
                "source_count": len(result.sources),
            }
        },
    )
    return result


def publish_scan(
    context: ExecutionContext,
    dependencies: RescanDependencies,
    navigation: NavigationScan,
    storage: StorageScan,
) -> ScanPublication:
    """重新核对每个数据集指纹，并在一个事务中发布未变化的索引结果。

    Args:
        context: 当前作业上下文，提供共享写锁及UTC时钟。
        dependencies: 与第一段相同的数据库和导航根。
        navigation: 未修改的第一段结果，包含原入口集合和消失候选。
        storage: 第二段结果；NOT_RUN时保留旧统计和可复用检查值。

    Returns:
        只有session_scope退出并提交成功才返回ScanPublication；变化者跳过并保留旧行及提示。
        全量成功是一次原子替换，读者只看到发布前或发布后；不逐数据集单独提交。

    Raises:
        JobCancelledError: 等锁或进入保护段前取消，旧索引保留。
        WorkerStoppingError: 等锁或进入保护段前停止，交框架恢复。
        ConflictError: 导航锁等待超限或数据库事务竞争。
        InputError: 索引损坏、复核预算越界，不能安全形成替换计划。
        ExternalError: 复核导航整体不可读或事务提交失败，旧索引保留。
        DefectError: 阶段身份/导航根不匹配、时钟非法或计划执行不一致。

    Side Effects:
        context.write_navigation中先重算指纹，再plan_index_replacement，最后session_scope内replace_index。
        事务提交前持续持锁，防止平台写入插队；第二段结果只应用到通过复核的数据集。
        不修改导航和存储根；失败不留下半套新索引，已提交结果不因随后日志故障撤回。

    Time Semantics:
        指纹计算在写事务外但在写锁内；每次重算传原known_entry_paths以检出消失和改身份。
        禁止锁内嵌套取锁，取消/停止延后至提交并放锁后的检查点；手工修改仅能尽力检测。
    """

    def publish() -> ScanPublication:
        observed = _fingerprints.collect(dependencies.nav_root, context.reporter.check_cancelled)
        current = tuple(
            _fingerprints.select(
                dependencies.nav_root,
                item.dataset_id,
                tuple(entry.path for entry in item.fingerprint.entries),
                observed,
                context.reporter.check_cancelled,
            )
            for item in navigation.datasets
        )
        plan = plan_index_replacement(
            navigation, storage, current, committed_at=context.clock.now()
        )
        with session_scope(dependencies.engine) as session:
            result = replace_index(session, plan)
        for group in plan.notices:
            for sample in group.diagnostics.samples:
                context.reporter.diagnostic(sample)
        return result

    return context.write_navigation(lambda: None, publish)
