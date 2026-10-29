"""数据集浏览服务（领域层，M1-03、ADR 0006），只读索引/导航文件，写偏好或作业行。

复用 session_scope、账号事务重验、JobService.submit 和第01张的读取/指纹能力；
不自行实现队列、哈希或 JSON 解析器。导航原文读取复用 datasets._io 的描述符边界，
禁止 resolve/exists/stat 跟随数据链接。型号读取器由装配方提供，不能硬编码业务型号。
"""

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.accounts.service import authorize_job_actor
from rdp.infra.diagnostics import DefectError
from rdp.jobs.dataset_browser.commands import DATASET_SIZING_JOB_TYPE as DATASET_SIZING_JOB_TYPE
from rdp.jobs.dataset_browser.commands import DatasetCommands
from rdp.jobs.dataset_browser.queries import DatasetQueries, QueryAccess, SubtasksDocument
from rdp.jobs.dataset_browser.queries import (
    read_unregistered_robot_models as read_unregistered_robot_models,
)
from rdp.jobs.dataset_browser.schemas import (
    DatasetDetailResponse,
    DatasetFilterOptions,
    DatasetFilters,
    DatasetListQuery,
    DatasetListResponse,
    DatasetPanelResponse,
    DatasetTreesResponse,
    Layout,
    LayoutResponse,
    RobotModelOption,
)
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobRecord


class DatasetBrowserService:
    """每次请求独立短事务；入口注入配置，实例不持有会话或存储根访问能力。"""

    def __init__(
        self,
        engine: Engine,
        nav_root: Path,
        jobs: JobService,
        read_robot_models: Callable[[Session], tuple[RobotModelOption, ...]],
    ) -> None:
        """绑定索引、导航根、作业提交与型号映射读取能力。

        Args:
            engine: 受管SQLite引擎，须已迁移；调用者负责生命周期。
            nav_root: 配置中的绝对导航目录，不含..；仅保存路径，不检查存储根。
            jobs: 共用同一引擎的M0作业服务，登记表由入口构造，不在这里导入执行函数。
            read_robot_models: 必填只读会话回调；M1用read_unregistered_robot_models，
                M3读取型号表。返回按编号排序的唯一型号，标签最多对应一个型号。

        Returns:
            无；得到可被多个请求共用的无请求状态服务。

        Raises:
            DefectError: 引擎不受管、两个服务数据库不一致、路径不是绝对路径或回调不可调用。

        Side Effects:
            仅保存依赖；不连接数据库、不读导航、不创建线程或登记作业。

        Time Semantics:
            启动期同步构造，无时钟、锁等待或后台轮询。
        """
        if jobs.engine is not engine:
            raise DefectError()
        self.queries = DatasetQueries(engine, nav_root, read_robot_models)
        self.commands = DatasetCommands(engine, jobs)

    def trees(self, request: JobRequest, filters: DatasetFilters) -> DatasetTreesResponse:
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
        return self.queries.trees(_access(request), filters)

    def list(self, request: JobRequest, query: DatasetListQuery) -> DatasetListResponse:
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
        return self.queries.list(_access(request), query)

    def filter_options(self, request: JobRequest) -> DatasetFilterOptions:
        """返回三个布局共用的候选值和默认机器人筛选模式。

        Args:
            request: 当前账号的会话、唯一UTC时刻和请求来源。

        Returns:
            全索引的型号、标签、FPS、来源选项和计数，每种未知项即使为零也保留。
            型号空目录时registered=False且默认robot_type；非空时默认robot_model。
            FPS用整数十进制文本传候选，标签保持原始大小写；M1来源计数仅unknown非零。

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
        return self.queries.filter_options(_access(request))

    def panel(self, request: JobRequest, dataset_id: str | None) -> DatasetPanelResponse:
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
        return self.queries.panel(_access(request), dataset_id)

    def detail(self, request: JobRequest, entry_path: str) -> DatasetDetailResponse:
        """读取选中入口的两份JSON原文，并与规范副本及索引指纹对照。

        Args:
            request: 可信会话和请求UTC时刻；原始请求不含文件系统根或操作者声明。
            entry_path: 索引返回的导航相对入口路径；不允许绝对路径、..、NUL或任意文件名。

        Returns:
            选中入口原始路径/信息的原文、独立规范信息、当前原文的数据块推导值与核验标签；
            原文保留未知字段和空白，解析失败仍可查看文本，缺失/非普通文件带五段诊断。
            规范副本不可用时不静默换用格式副本；子任务仅返回请求定位，不含正文。
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
        return self.queries.detail(_access(request), entry_path)

    def subtasks(self, request: JobRequest, entry_path: str) -> SubtasksDocument:
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
        return self.queries.subtasks(_access(request), entry_path)

    def submit_rescan(self, request: JobRequest, dataset_id: str) -> JobRecord:
        """为当前账号提交一个单数据集重新扫描作业。

        Args:
            request: M0 JobRequest，提交人和审计来源不可由客户端覆盖。
            dataset_id: 已入索引的永久编号，遵循RescanParameters范围，不能传None触发全量。

        Returns:
            JobService.submit已提交的queued记录；type_name使用catalog.RESCAN_TYPE，
            参数只有dataset_id，即使worker离线也返回排队记录。

        Raises:
            DatasetNotFoundError: 提交前编号不在索引。
            DatasetQueryError: 编号不满足已合并扫描参数约束。
            JobInputError: 登记表缺少扫描类型或登记模型拒绝参数。
            AuthenticationError: JobService写事务重验时身份失效。
            PasswordChangeRequiredError: 提交时账号须改密。
            InputError: 索引或作业记录损坏。
            ConflictError: 作业提交/操作日志写锁竞争或编号耗尽。
            ExternalError: 作业和审计事务失败。
            DefectError: 服务装配或注入时刻非法。

        Side Effects:
            只委托M0提交作业与操作日志，同事务写入；不调用扫描执行器、不写索引或导航。
            范围预查后导航变化由worker处理，不把本次预查当执行许可；失败不留半条作业。

        Time Semantics:
            复用请求唯一UTC时刻；普通写锁5秒、失败补记100毫秒，不在HTTP等待作业完成。
        """
        return self.commands.submit_rescan(request, dataset_id)

    def submit_sizing(self, request: JobRequest, dataset_id: str | None) -> JobRecord:
        """向已有队列提交手动统计大小，执行类型由第02张登记。

        Args:
            request: 当前会话及审计来源，使用当前账号而非系统身份。
            dataset_id: 已索引编号；None表示全量，拒绝附带存储根、IO优先级或路径。

        Returns:
            DATASET_SIZING_JOB_TYPE的新queued记录，parameters只有dataset_id；
            响应使用M0作业类型，大小结果由后续worker发布，提交时不假造新大小。

        Raises:
            DatasetNotFoundError: 非空编号未入索引。
            DatasetQueryError: 编号文本非法。
            JobInputError: 统计类型未登记或参数校验拒绝，不自行注册一个替代类型。
            AuthenticationError: 提交写事务中身份失效。
            PasswordChangeRequiredError: 账号须先改密。
            InputError: 数据库中的范围/作业数据损坏。
            ConflictError: 提交事务竞争或编号耗尽。
            ExternalError: 作业/操作日志持久化失败。
            DefectError: 统计提交装配、时钟或返回记录违反契约。

        Side Effects:
            M0同事务新增作业和提交日志，不import第02张模块、不遍历根、不在Web执行作业。

        Time Semantics:
            锁与补记预算沿用JobService.submit，不等待上次统计结束、不自动重试POST。
        """
        return self.commands.submit_sizing(request, dataset_id)

    def get_layout(self, request: JobRequest) -> LayoutResponse:
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
        return self.queries.get_layout(_access(request))

    def set_layout(self, request: JobRequest, layout: Layout) -> LayoutResponse:
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
        return self.queries.set_layout(_access(request), layout)


def _access(request: JobRequest) -> QueryAccess:
    """只传入当前身份的事务授权回调，不把M0作业服务交给查询层。"""

    def authorize(session: Session) -> int:
        actor = authorize_job_actor(session, request.identity, now=request.now)
        if actor.account_id is None:
            raise DefectError()
        return actor.account_id

    return QueryAccess(request.now, authorize)
