"""重新扫描作业装配（领域层，M1-01、ADR 0005/0006），不实现自己的锁、队列或恢复器。

类型执行器持有入口注入的数据库和导航配置；Web只登记相同参数模型，不获得文件访问能力。
生产登记通过build_rescan_definition显式加入JobRegistry，恢复、取消、结果均由M0框架收口。
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from rdp.infra.config import StorageRootConfig
from rdp.infra.storage import StorageAccessChecker
from rdp.jobs.datasets.scan_types import NavigationScan, ScanPublication, StorageScan
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.registry import JobDefinition


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
        storage: 第02张只读访问检查器；本票明确传None，不构造真实检查器。
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
        raise NotImplementedError


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
    raise NotImplementedError


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
    raise NotImplementedError


def scan_storage(
    navigation: NavigationScan,
    dependencies: RescanDependencies,
    *,
    checkpoint: Callable[[], None],
) -> StorageScan:
    """返回明确的存储检查未执行结果，保持第二段交接形状。

    Args:
        navigation: 第一段完整快照，不允许把它变成存储遍历请求。
        dependencies: 显式扫描依赖，本函数不调用storage检查器或读取root.path。
        checkpoint: 必填控制检查点，进入时调用一次，取消后不产生结果。

    Returns:
        StorageScan(stage=NOT_RUN)，roots/links/sources/findings为空，warning_count=0。
        未执行本身不是存储根离线，不能清掉旧大小或把链接标为可用。

    Raises:
        JobCancelledError: 检查点收到取消。
        WorkerStoppingError: 检查点收到停止。
        DefectError: 第一段快照或依赖形状非法。

    Side Effects:
        无；不读存储根或挂载表、不获取导航锁、不修改第一段值，不提交数据库。

    Time Semantics:
        只在第一段放锁后的阶段边界调用，无等待、无重试、不产生虚构检查时间。
    """
    raise NotImplementedError


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
    raise NotImplementedError
