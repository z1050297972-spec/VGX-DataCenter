"""创建操作的提交与预览读取（Web 可调用的领域层，M1-08、ADR 0006）。

只持有数据库、状态路径及 M0 JobService，不持有导航根或存储检查器。
写作业参数只有 preview_job_id；提醒不是锁，最终一致性由第 07 张写锁内复核保证。
"""

from dataclasses import dataclass

from sqlalchemy import Engine

from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.create_models import DatasetPreviewParameters, LinkPreviewParameters
from rdp.jobs.navwrite.create_views import CreationOptions, CreationPreviewView, QueuedNavigationJob
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobRecord


@dataclass(frozen=True)
class CreationAccess:
    """Web 创建接口的最小依赖，不能借此读取真实存储目标。

    Attributes:
        engine: 已迁移的受管数据库引擎，与 jobs.engine 是同一对象。
        paths: 已初始化状态目录，只读 nav-previews；不发现用户真实部署路径。
        jobs: 已完成类型登记的 M0 作业提交服务。
    """

    engine: Engine
    paths: StatePaths
    jobs: JobService


@dataclass(frozen=True)
class CreationSubmission:
    """写入提交的结果，排队提醒需要额外确认时不会创建作业。

    Attributes:
        job: 已提交 nav_write_apply 的 queued 记录；有未确认提醒时为 None。
        queued_jobs: 本次提交前观察到的同数据集排队写作业，编号升序；不包含本次新作业。
    """

    job: JobRecord | None
    queued_jobs: tuple[QueuedNavigationJob, ...]


def read_creation_options(access: CreationAccess, request: JobRequest) -> CreationOptions:
    """读取创建表单使用的登记格式、已有版本与数据来源候选。

    Args:
        access: Web 最小依赖，不提供文件访问器。
        request: 必填认证身份、请求 UTC 时刻及审计来源；不接受客户端操作者。

    Returns:
        登记格式和来源的完整候选；版本只取索引，空索引仍返回全部登记格式。

    Raises:
        AuthenticationError: 读事务中会话失效或账号不可用。
        PasswordChangeRequiredError: 账号需要先改密。
        InputError: 索引版本字段损坏，不能当作空候选。
        ConflictError: 读取候选的数据库锁超限。
        ExternalError: 版本索引查询失败。
        DefectError: 依赖数据库不一致或注入时刻非法。

    Side Effects:
        无（只读索引，按现有账号服务重验身份；不读取版本目录或 meta/info.json）。

    Time Semantics:
        单次事务快照，沿用 BUSY_TIMEOUT_MS，无轮询或自动重试。
    """
    raise NotImplementedError


def submit_link_preview(
    access: CreationAccess, request: JobRequest, parameters: LinkPreviewParameters
) -> JobRecord:
    """以当前账号提交现有数据集的只读建链预览作业。

    Args:
        access: 共用同一引擎的 M0 作业服务与状态路径。
        request: 身份、来源 IP、请求编号及唯一 UTC 时刻，全部由服务器提供。
        parameters: dataset_id、第一链接及格式选择，不含导航根或执行计划。

    Returns:
        LINK_PREVIEW_TYPE 的新 queued 记录；worker 离线时仍可提交。

    Raises:
        DatasetNotFoundError: 预查索引中 dataset_id 不存在。
        JobInputError: 参数超 16 KiB、格式选择重复或类型未登记/不兼容。
        AuthenticationError: 提交事务内当前账号会话失效。
        PasswordChangeRequiredError: 提交账号必须改密。
        InputError: 索引或历史作业数据损坏。
        ConflictError: M0 作业提交或操作日志事务竞争、编号耗尽。
        ExternalError: 作业或提交日志持久化失败，整次提交回滚。
        DefectError: 引擎、审计来源或时钟违反既有提交契约。

    Side Effects:
        只调用 JobService.submit，作业及提交操作日志同事务；不执行 builder，
        目标存在性和存储根身份均由 worker 判断，HTTP 不做目标预查。

    Time Semantics:
        使用 request.now；锁预算沿用 JobService.submit，不等待预览结束、不重试 POST。
    """
    raise NotImplementedError


def submit_dataset_preview(
    access: CreationAccess, request: JobRequest, parameters: DatasetPreviewParameters
) -> JobRecord:
    """提交新增数据集的只读预览，不在 Web 中分配数据集编号。

    Args:
        access: 完成生产类型登记的 M0 作业服务。
        request: 真实提交人会话及审计上下文；必填，不使用系统身份替代。
        parameters: 数据集名、必填来源、第一链接和格式位置；不接受客户端编号。

    Returns:
        DATASET_PREVIEW_TYPE 的 queued 作业记录；重名、目标、预计编号由 worker 生成预览时确认。

    Raises:
        JobInputError: 输入模型拒绝、格式选择重复、参数超作业预算或预览类型未登记。
        AuthenticationError: 会话被撤销或账号停用/删除。
        PasswordChangeRequiredError: 当前账号尚未完成强制改密。
        InputError: 作业持久化数据损坏。
        ConflictError: 队列提交或提交日志锁竞争、编号耗尽。
        ExternalError: M0 提交事务 I/O 失败，无半条作业记录。
        DefectError: 请求时刻、身份或服务装配非法。

    Side Effects:
        M0 原子新增预览作业和提交日志；不建入口、不分配编号、不读写导航或数据盘。

    Time Semantics:
        请求提交后立即返回；使用同一次 request.now，不因目标不可达阻塞 Web。
    """
    raise NotImplementedError


def read_creation_preview(
    access: CreationAccess, request: JobRequest, preview_job_id: int
) -> CreationPreviewView:
    """投影成功的创建预览，并补充提交前的同数据集排队提醒。

    Args:
        access: 状态文件只读访问与数据库依赖，无存储根能力。
        request: 当前成员或管理员请求，读事务内重验，不限制为预览原提交人。
        preview_job_id: 1 至 MAX_SQLITE_INTEGER 的整数，对应两种创建预览类型之一。

    Returns:
        CreationPreviewView；文件/链接/根/数据块/格式入口变化来自保存的 report.creation，
        不返回 plan.steps[].after_content、JSON 全文或可被客户端修改的计划。
        queued_jobs 从数据库查 writes_navigation 的排队作业，通过其预览计划关联编号，
        不只匹配参数顶层 dataset_id，也不把只读预览算入写提醒。

    Raises:
        JobNotFoundError: 作业编号不存在。
        InputError: 类型不是创建预览、预览未 completed 或结果不是 succeeded/succeeded_with_warnings、
            预览缺失/损坏/过七天保留期、操作与参数不匹配，或排队提醒超过既有扫描预算。
        AuthenticationError: 读取时会话失效。
        PasswordChangeRequiredError: 账号必须先改密。
        ConflictError: 预览记录查询锁超限。
        ExternalError: 状态文件或队列数据库读取失败，不伪装成无排队提醒。
        DefectError: 创建预览缺少 creation 差异或报告与计划计数不一致。

    Side Effects:
        无（复用 read_preview 只读状态目录，查询作业与身份；不重算 builder、不写导航）。

    Time Semantics:
        created_at 保留预览时刻；排队提醒反映读取时已提交状态，不是执行许可或互斥锁。
        前端在预览成功后读取一次、确认前再读一次，预览任务仍运行时只轮询 M0 作业接口。
    """
    raise NotImplementedError


def submit_creation_write(
    access: CreationAccess,
    request: JobRequest,
    preview_job_id: int,
    acknowledged_queue_job_ids: tuple[int, ...],
) -> CreationSubmission:
    """确认同一份创建预览后提交公共 nav_write_apply 作业。

    Args:
        access: 共用 M0 JobService 与状态目录，不能提供客户端计划写入途径。
        request: 本次确认者身份及审计上下文，写作业提交人是确认者。
        preview_job_id: 成功的创建预览编号，整数 1 至 MAX_SQLITE_INTEGER。
        acknowledged_queue_job_ids: 用户已看到并确认的排队写作业编号，去重整数元组；
            首次为空，有未确认的当前排队编号时先返回提醒而不提交作业。

    Returns:
        CreationSubmission；未确认提醒时 job=None，queued_jobs 列出当前排队项；
        否则 JobService.submit 新建 nav_write_apply，参数只有整数 preview_job_id。
        已确认提醒不是跳过 L12 校验的授权，状态漂移由 worker 以冲突失败并列差异。

    Raises:
        JobNotFoundError: 预览作业不存在。
        JobInputError: 编号非法、重复确认编号、参数或 NAV_APPLY_TYPE 未登记。
        InputError: 预览类型/成功状态/文件/计划不合法，规则同 read_creation_preview。
        AuthenticationError: 确认账号在实际提交事务内失效。
        PasswordChangeRequiredError: 确认账号必须改密。
        ConflictError: M0 提交事务或提醒查询竞争，什么都不提交。
        ExternalError: 读取预览、排队作业或作业/日志持久化失败。
        DefectError: 依赖不一致或报告/计划违反创建模型契约。

    Side Effects:
        先读取同一份预览并刷新提醒，再委托 JobService.submit 原子写作业与提交日志；
        未确认分支不写业务行。导航恢复失败标记存在时仍允许排队，由既有 worker 门禁挡住执行。
        不运行 builder、不写导航、不重新分配编号或替换目标。

    Time Semantics:
        提醒是提交前数据库快照，快照之后新来的作业仍靠写锁内 L12 复核保护；
        不把两个 JobService 事务嵌套为一个长事务。POST 不自动重试，进度转到 M0 作业页。
    """
    raise NotImplementedError
