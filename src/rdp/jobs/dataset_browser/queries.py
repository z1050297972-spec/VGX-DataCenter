"""数据集查询与个人偏好（领域层，M1-03），不依赖作业登记、执行或存储访问。

身份重验由兼容入口传入只读事务授权回调；回调只调用M0账号授权，不携带作业或文件能力。
索引使用SQLAlchemy，导航读取与指纹沿用第01张实现，全部时间由请求显式传入。
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.dataset_browser import (
    _documents,
    _index,
    _listing,
    _panel,
    _preferences,
    _scope,
    _trees,
)
from rdp.jobs.dataset_browser.preference_models import DatasetLayoutPreferenceRow
from rdp.jobs.dataset_browser.schemas import (
    DataOrigin,
    DatasetDetailResponse,
    DatasetFilterOptions,
    DatasetFilters,
    DatasetListQuery,
    DatasetListResponse,
    DatasetPanelResponse,
    DatasetTreesResponse,
    FilterOption,
    Layout,
    LayoutResponse,
    RobotModelOption,
)
from rdp.jobs.datasets import reading


@dataclass(frozen=True)
class QueryAccess:
    """查询事务的授权能力，身份来自入口而非用户参数。

    Attributes:
        now: 请求唯一aware时刻，UTC微秒。
        authorize: 必填账号事务重验回调，传当前Session；成功返回当前账号正整数编号；失效时抛M0账号异常，不写业务表。
    """

    now: datetime
    authorize: Callable[[Session], int]


@dataclass(frozen=True)
class SubtasksDocument:
    """单独传输的子任务原字节和响应头信息，不放进详情 JSON 或响应模型编码器。

    Attributes:
        content: 导航层普通文件的完整原字节，0至MAX_DOCUMENT_BYTES字节；不截断、不重排键。
        sha256: 这份content的64位小写SHA-256摘要，不能取另一次文件读取的摘要。
        index_stale: 本次指纹与索引不同、不可验证或发送内容摘要与本次指纹不同时True。
        observed_at: 请求注入的UTC时刻，非文件mtime，非多文件原子观察保证。
    """

    content: bytes
    sha256: str
    index_stale: bool
    observed_at: datetime


def read_unregistered_robot_models(session: Session) -> tuple[RobotModelOption, ...]:
    """提供尚无型号登记模块时的空目录，作为M1生产装配的显式适配器。

    Args:
        session: 本请求已授权的只读数据库会话，不自行开启或提交事务。

    Returns:
        空元组，明确没有登记型号；M3装配真实表读取器后移除此适配器，筛选服务与HTTP类型不变。

    Raises:
        无。

    Side Effects:
        无；不尝试查询尚不存在的型号表，不按数据标签自动创建平台型号。

    Time Semantics:
        与本请求索引查询共享会话生命周期；不缓存空结果，不读取墙钟。
    """
    return ()


class DatasetQueries:
    """持有只读查询依赖；布局写入使用同一账号范围，不包含作业提交能力。"""

    def __init__(
        self,
        engine: Engine,
        nav_root: Path,
        read_robot_models: Callable[[Session], tuple[RobotModelOption, ...]],
    ) -> None:
        """绑定索引、导航根与型号映射读取能力，不取得作业提交能力。

        Args:
            engine: 受管SQLite引擎，须已迁移；调用者负责生命周期。
            nav_root: 配置中的绝对导航目录，不含..；仅保存路径，不检查存储根。
            read_robot_models: 必填只读会话回调；M1用read_unregistered_robot_models，
                M3读取型号表。返回按编号排序的唯一型号，标签最多对应一个型号。

        Returns:
            无；得到可被多个请求共用的无请求状态服务。

        Raises:
            DefectError: 引擎不受管、路径不是绝对路径或回调不可调用。

        Side Effects:
            仅保存依赖；不连接数据库、不读导航、不创建线程或登记作业。

        Time Semantics:
            启动期同步构造，无时钟、锁等待或后台轮询。
        """
        if (
            not engine.get_execution_options().get("rdp_managed")
            or not nav_root.is_absolute()
            or ".." in nav_root.parts
            or not callable(read_robot_models)
        ):
            raise DefectError()
        self.engine = engine
        self.nav_root = nav_root
        self.read_robot_models = read_robot_models

    def trees(self, request: QueryAccess, filters: DatasetFilters) -> DatasetTreesResponse:
        """从索引构造两棵共用筛选条件的有界目录树。

        Args:
            request: 当前账号会话、请求UTC时刻和审计来源，全部显式提供。
            filters: 不同维度取交集；路径按完整分量前缀，非法组合不能回退全量。

        Returns:
            两个视图根加按路径升序的平铺节点；数量按已知编号去重，大小按入口相加。
            空树返回零，未知大小返回已知小计及未知入口数；无扫描时indexed_at=None。
            只显示索引已有的格式/版本目录，不扫描磁盘来补空版本目录。

        Raises:
            DatasetQueryError: 非法路径前缀、负FPS、版本缺格式或task与格式筛选冲突。
            InputError: 索引损坏或超过MAX_SCAN_ENTRIES，不能截断为完整树。
            AuthenticationError: 读事务中会话已失效或账号停用。
            PasswordChangeRequiredError: 事务中账号被标记须改密。
            ConflictError: 索引读锁等待超限。
            ExternalError: 查询失败或型号读取器数据库I/O失败。
            DefectError: 型号映射重复、返回类型或注入时刻非法。

        Side Effects:
            无（只读索引和型号映射，不打开任何导航文件、挂载表或存储根）。

        Time Semantics:
            单个读事务保证本次树聚合一致；沿用BUSY_TIMEOUT_MS，不重试。
            大小时间是原统计时间范围，不改成请求时刻；不同请求间允许扫描发布变化。
        """
        _listing.validate(filters)
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            request.authorize(session)
            index = _index.load(session, self.read_robot_models)
            rows = tuple(
                entry
                for item in _listing.items(index)
                if _listing.matches(item, filters)
                for entry in item.entries
                if _listing.entry_matches(entry, filters)
            )
        return DatasetTreesResponse(
            nodes=_trees.nodes(rows),
            indexed_at=next((scan.committed_at for scan in index.scans if scan.is_current), None),
        )

    def list(self, request: QueryAccess, query: DatasetListQuery) -> DatasetListResponse:
        """按规范入口的索引信息筛选并分页返回数据集和损坏入口。

        Args:
            request: 已认证身份与同请求时刻/来源，成员和管理员范围相同。
            query: 共享筛选及offset、limit；上限分别MAX_SCAN_ENTRIES和BROWSER_PAGE_LIMIT。

        Returns:
            按名称、dataset_id、入口路径排序；同编号只一行，无编号入口各一行。
            型号映射为空时任意具体型号匹配空集；未知型号匹配无映射的数据集。
            元信息优先唯一规范入口；没有或重复规范入口则取格式入口并集，并保留面板发现。
            当前筛选匹配任一入口即入选，响应entries仍含全部位置；不返回JSON正文。

        Raises:
            DatasetQueryError: 分页或筛选组合非法；拒绝负FPS、绝对或穿越路径。
            InputError: 索引字段损坏，不能造空对象替代。
            AuthenticationError: 当前会话在读取时失效。
            PasswordChangeRequiredError: 当前账号必须改密。
            ConflictError: 分页查询锁超时。
            ExternalError: 列表或型号目录读取失败。
            DefectError: 型号标签多重归属或查询投影违反展示模型。

        Side Effects:
            只读索引与型号表，total和items在同一读事务；不刷新索引或写查看日志。

        Time Semantics:
            行保留自身索引代次时间；分页跨请求不承诺固定快照，扫描发布后前端重新取首页。
            同步查询，数据库锁最多BUSY_TIMEOUT_MS，无无限等待或自动重试。
        """
        _listing.validate(query)
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            request.authorize(session)
            index = _index.load(session, self.read_robot_models)
            rows = tuple(item for item in _listing.items(index) if _listing.matches(item, query))
        return DatasetListResponse(
            items=rows[query.offset : query.offset + query.limit],
            total=len(rows),
            offset=query.offset,
            limit=query.limit,
            indexed_at=next((scan.committed_at for scan in index.scans if scan.is_current), None),
        )

    def filter_options(self, request: QueryAccess) -> DatasetFilterOptions:
        """返回三个布局共用的候选值和默认机器人筛选模式。

        Args:
            request: 当前账号的会话、唯一UTC时刻和请求来源。

        Returns:
            全索引的型号、标签、FPS、来源选项和计数，每种未知项即使为零也保留。
            型号空目录时registered=False且默认robot_type；非空时默认robot_model。
            FPS用整数十进制文本传候选，标签保持原始大小写；来源按索引中的稳定编码计数。

        Raises:
            AuthenticationError: 身份失效，不能提供索引统计。
            PasswordChangeRequiredError: 当前账号须先改密。
            InputError: 索引元信息违反已合并字段约束。
            ConflictError: 候选聚合读锁超限。
            ExternalError: 型号目录或索引数据库不可读。
            DefectError: 型号编号重复、标签多重映射或时钟不是aware。

        Side Effects:
            只查索引和注入型号目录，不创建型号、不读取meta/info.json或14项Markdown。

        Time Semantics:
            每次读同一事务快照，型号登记后下一请求生效；不持久缓存“没有登记型号”。
        """
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            request.authorize(session)
            index = _index.load(session, self.read_robot_models)
            facts = [_index.metadata(index, row) for row in index.datasets]
        return DatasetFilterOptions(
            robot_models_registered=bool(index.models),
            default_robot_filter="robot_model" if index.models else "robot_type",
            robot_models=index.models,
            robot_model_options=_options([set(value[2]) or {None} for value in facts]),
            robot_types=_options([set(value[0]) for value in facts]),
            fps=_options([set(value[1]) for value in facts]),
            data_origins=tuple(
                FilterOption(
                    value=origin.value,
                    label=label,
                    count=sum(row.data_origin == origin.value for row in index.datasets),
                )
                for origin, label in zip(
                    DataOrigin,
                    ("真机采集", "UMI采集", "ego采集", "仿真生成", "开源下载", "未知"),
                    strict=True,
                )
            ),
        )

    def panel(self, request: QueryAccess, dataset_id: str | None) -> DatasetPanelResponse:
        """读取四组两级聚合发现以及最近扫描的存储根顶部提示。

        Args:
            request: 已登录账号请求上下文，不要求管理员。
            dataset_id: 非空永久编号；None查全局面板，指定时只取该数据集发现并保留全局根提示。

        Returns:
            按PanelGroup/PanelSeverity声明顺序、来源和规则排序的发现；总数为全量，
            样例按对象路径排序后取DIAGNOSTIC_SAMPLE_LIMIT条；不按样例数重算总数。
            最近扫描根状态online=False提示离线，None提示未检查，保留原checked_at。

        Raises:
            DatasetNotFoundError: 指定编号不在索引。
            DatasetQueryError: 非空范围编号形状不合法。
            AuthenticationError: 读取时会话已撤销。
            PasswordChangeRequiredError: 强制改密未完成。
            InputError: 已存发现、根状态或计数损坏。
            ConflictError: 面板聚合事务锁竞争。
            ExternalError: 索引发现读取失败。
            DefectError: 五段诊断或聚合映射违反类型契约。

        Side Effects:
            只读发现和扫描元数据；不运行检查、不将面板问题算成新作业失败、不访问根路径。

        Time Semantics:
            发现可能来自各数据集不同代次；只在下次扫描发布后变化，不宣称实时检查。
        """
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            request.authorize(session)
            _scope.require_dataset(session, dataset_id)
            return _panel.snapshot(session, dataset_id)

    def detail(self, request: QueryAccess, entry_path: str) -> DatasetDetailResponse:
        """读取选中入口的两份JSON原文，并与规范副本及索引指纹对照。

        Args:
            request: 可信会话和请求UTC时刻；原始请求不含文件系统根或操作者声明。
            entry_path: 索引返回的导航相对入口路径；不允许绝对路径、..、NUL或任意文件名。

        Returns:
            选中入口原始路径/信息的原文、独立规范信息、当前原文的数据块推导值与核验标签；
            原文保留未知字段和空白，解析失败仍可查看文本，缺失/非普通文件带五段诊断。
            规范副本不可用时不静默换用格式副本；子任务仅返回请求定位，不含正文。
            provenance 返回规范入口当前来源和标注印记，缺文件与坏文件分态表达。
            links与大小来自索引。用第01张L12指纹比较全部入口；差异、不可验证或本次原文
            摘要不等于观察指纹均标index_stale=True，不以mtime判断，不更新索引。

        Raises:
            DatasetNotFoundError: entry_path未入索引；已入索引但文件消失仍返回带诊断详情。
            DatasetQueryError: 路径文本越界或不符合入口定位约束。
            AuthenticationError: 读事务中会话失效。
            PasswordChangeRequiredError: 账号须先改密。
            InputError: 索引损坏或L12整体读取预算超限。
            ConflictError: 查询索引时数据库忙。
            ExternalError: 索引读取或整个导航根/视图枚举失败；单文件失败局部降级。
            DefectError: 推导字段、时刻或依赖装配违反契约。

        Side Effects:
            先读索引并关闭事务，再经第01张O_NOFOLLOW描述符边界读导航普通文件/链接自身；
            复用parse_document、derive_source_entry_path和fingerprint_dataset，不跟随链接目标。
            L12检查会读取子任务字节用于摘要/身份核对，但不把正文塞进详情响应；不拿worker锁。

        Time Semantics:
            文件I/O不占数据库事务；沿用MAX_DOCUMENT_BYTES、MAX_SCAN_BYTES/ENTRIES的预算。
            不重试，无法保证多个文件原子快照；读期间改变保守标过期，前端可提交重新检查。
        """
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            request.authorize(session)
            index = _index.load(session, self.read_robot_models)
            row = _documents.selected(index, entry_path)
            links = _documents.links(session, row.path)
            item = next(
                item
                for item in _listing.items(index)
                if any(entry.entry_path == row.path for entry in item.entries)
            )
        original = _documents.document(self.nav_root, row, "原始路径.json")
        information = _documents.document(self.nav_root, row, "数据集信息.json")
        canonical_row = next(
            (entry for entry in index.entries if entry.path == item.canonical_entry_path), None
        )
        canonical = (
            None
            if canonical_row is None
            else information
            if canonical_row.path == row.path
            else _documents.document(self.nav_root, canonical_row, "数据集信息.json")
        )
        sources, projection_issues, projection_stable = _documents.project(
            self.nav_root, row, original.sha256, information.sha256
        )
        current, stale = _documents.current_fingerprint(self.nav_root, index, row)
        documents = (original, information) + ((canonical,) if canonical is not None else ())
        stale = (
            stale
            or not projection_stable
            or any(
                not _documents.digest_matches(
                    current, document.entry_path, document.name, document.sha256
                )
                for document in documents
            )
        )
        return DatasetDetailResponse(
            provenance=_documents.provenance(self.nav_root, canonical_row),
            entry=_listing.entry(row),
            entries=item.entries,
            canonical_entry_path=item.canonical_entry_path,
            original_paths=original,
            information=information,
            canonical_information=canonical,
            sources=sources,
            links=links,
            dataset_size=item.size,
            subtasks_entry_path=row.path,
            index_stale=stale,
            indexed_at=item.indexed_at,
            observed_at=_moment(request.now),
            diagnostics=tuple(issue for document in documents for issue in document.diagnostics)
            + projection_issues,
        )

    def subtasks(self, request: QueryAccess, entry_path: str) -> SubtasksDocument:
        """独立读取子任务原字节，提供有界的大文件传输内容和过期标记。

        Args:
            request: 当前账号身份与UTC时刻，在文件读取前完成事务身份重验。
            entry_path: 已入索引的相对入口路径，文件名固定子任务.json，不接受目标路径。

        Returns:
            SubtasksDocument；约14MB文件一次完整读取后返回原字节，最多MAX_DOCUMENT_BYTES。
            不经Pydantic JSON序列化、不包进JSON字符串；未知schema或坏JSON原文仍交查看器。
            index_stale覆盖本次发送字节的哈希与索引/L12观察不一致，不能使用另一次读取的摘要冒充。

        Raises:
            DatasetNotFoundError: 入口未入索引；文件缺失使用InputError，不混同不存在的数据集。
            DatasetQueryError: 路径非法、越界或含控制分量。
            InputError: 子任务缺失、非普通文件、非法UTF-8或超MAX_DOCUMENT_BYTES；不返回部分正文。
            AuthenticationError: 会话失效或账号不可用。
            PasswordChangeRequiredError: 账号强制改密。
            ConflictError: 索引查询锁超时，或文件在读取期间改变，尚未发送任何正文。
            ExternalError: 文件权限/磁盘I/O或数据库失败。
            DefectError: 文件摘要、时刻或服务装配错误。

        Side Effects:
            只读导航；先完成受限读取和检查，再交HTTP发送，失败仍能走五段诊断。
            拒绝目录/JSON软链接及FIFO；不以FileResponse重新按路径打开文件，避免检查后换链。

        Time Semantics:
            同步读取在FastAPI线程池，单文件预算32MiB来自第01张，约14MB不是新上限。
            无压缩、后台任务或自动重试；客户端收到text/plain后在工作线程解析。
        """
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            request.authorize(session)
            index = _index.load(session, self.read_robot_models)
            row = _documents.selected(index, entry_path)
        content = _documents.subtasks_bytes(self.nav_root, row)
        parsed = reading.parse_document(_documents.location(row), "子任务.json", content)
        if parsed.sha256 is None:
            raise DefectError()
        current, stale = _documents.current_fingerprint(self.nav_root, index, row)
        return SubtasksDocument(
            content,
            parsed.sha256,
            stale or not _documents.digest_matches(current, row.path, "子任务.json", parsed.sha256),
            _moment(request.now),
        )

    def get_layout(self, request: QueryAccess) -> LayoutResponse:
        """读取当前账号跨会话共用的最后一次布局选择。

        Args:
            request: 当前已认证账号身份；账号编号从重验的会话得到，不能由查询参数指定。

        Returns:
            已保存的A/B/C及UTC修改时刻；没有记录时A、updated_at=None，不创建默认行。

        Raises:
            AuthenticationError: 账号停用、删除或会话无效。
            PasswordChangeRequiredError: 当前账号须先改密。
            InputError: 已保存布局不是A/B/C或时间字段损坏。
            ConflictError: 偏好读锁竞争超过普通预算。
            ExternalError: 布局表未迁移或数据库I/O失败，不伪装为默认A。
            DefectError: 引擎或注入时刻不满足契约。

        Side Effects:
            只读当前账号的一行，不触碰数据集索引、导航层或其他账号偏好，不记查看日志。

        Time Semantics:
            换会话下一次读取立即可见已提交选择；读锁沿用BUSY_TIMEOUT_MS，不缓存会话副本。
        """
        _moment(request.now)
        with session_scope(self.engine, read_only=True) as session:
            account_id = request.authorize(session)
            return _preferences.read(session, account_id)

    def set_layout(self, request: QueryAccess, layout: Layout) -> LayoutResponse:
        """原子保存当前账号的个人布局偏好，不写操作日志。

        Args:
            request: 身份、唯一UTC时刻和必填审计上下文，写事务内再次重验账号。
            layout: 严格A/B/C之一；大小写不自动修正，不存筛选或当前选中项。

        Returns:
            已提交布局和updated_at；同值请求保持原时刻且不重复写入；首次保存A也建行。

        Raises:
            DatasetQueryError: 布局不是允许值。
            AuthenticationError: 写事务内账号已停用/删除或会话失效。
            PasswordChangeRequiredError: 事务内强制改密。
            InputError: 原偏好或账号数据损坏。
            ConflictError: 写锁、外键或唯一约束竞争。
            ExternalError: 偏好写入失败，整体回滚，保留原选择。
            DefectError: 请求时刻或领域装配错误。

        Side Effects:
            BEGIN IMMEDIATE内重验身份后upsert当前账号一行；失败不改变偏好，不写操作日志。
            删除账号级联删除偏好；重建数据集索引不删除偏好。

        Time Semantics:
            最后成功串行提交者生效，不按客户端时刻排序；UTC墙钟回拨时updated_at保留原值最大值。
            普通锁5秒；不跨请求持Session，不在事务内做文件I/O。
        """
        layout = _preferences.choice(layout)
        moment = _moment(request.now)
        with session_scope(self.engine) as session:
            account_id = request.authorize(session)
            _preferences.read(session, account_id)  # 写入前先验证旧记录与表可用性。
            row = session.get(DatasetLayoutPreferenceRow, account_id)
            if row is None:
                session.add(
                    DatasetLayoutPreferenceRow(
                        account_id=account_id, layout=layout, updated_at=moment
                    )
                )
            elif row.layout != layout:
                # 事务串行决定最后选择，墙钟回拨不能倒退原修改时间。
                row.layout = layout
                row.updated_at = max(row.updated_at, moment)
            session.flush()
            result = _preferences.read(session, account_id)
        return result


def _options(groups: list[set[str | int | None]]) -> tuple[FilterOption, ...]:
    """候选来自完整索引，未知选项始终保留且置于最后。"""
    values: set[str | int | None] = {value for group in groups for value in group}
    values.add(None)
    ordered = sorted(values, key=lambda value: (value is None, isinstance(value, str), value or 0))
    return tuple(
        FilterOption(
            value="unknown" if value is None else str(value),
            label="未知" if value is None else str(value),
            count=sum(value in group for group in groups),
        )
        for value in ordered
    )


def _moment(value: datetime) -> datetime:
    """非法注入时刻是装配缺陷，不能把naive时间默认为本地时间或归为用户参数错误。"""
    try:
        return ensure_utc(value)
    except (AttributeError, TypeError, ValueError, OverflowError) as error:
        raise DefectError() from error
