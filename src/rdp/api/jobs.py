"""作业 HTTP 入口（08）；全局 Origin→认证→强制改密→路由→参数，所有登录账号可访问。

不使用 get_admin_context，不执行作业或访问存储根；沿用第 6 张账号上下文和第 7 张审计来源。
应用工厂只登记路由；第 11 张 Web 入口显式构造 registry/StatePaths 并调用 configure_jobs。
"""

import re
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field
from pathlib import Path
from typing import Annotated, cast

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from sqlalchemy import Engine

from rdp.api._account_context import identity
from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.job_schemas import (
    JobFilters,
    JobListResponse,
    JobLogResponse,
    JobResponse,
    SubmitJobPayload,
    WorkerStatusResponse,
)
from rdp.api.scheduling_schemas import SchedulingResponse
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    ExternalError,
)
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.infra.state import StatePaths
from rdp.jobs.errors import JobInputError
from rdp.jobs.example import CountParameters
from rdp.jobs.logs import read_log_tail
from rdp.jobs.registry import JobRegistry
from rdp.jobs.resource_examples import GpuExampleParameters, NavigationExampleParameters
from rdp.jobs.scheduling_service import SchedulingService
from rdp.jobs.scheduling_types import SchedulingCatalog
from rdp.jobs.service import JobRequest, JobService
from rdp.jobs.types import JobQuery, JobRecord
from rdp.jobs.worker import heartbeat_online

router = APIRouter(prefix="/api/jobs", tags=["jobs"])
worker_router = APIRouter(prefix="/api/worker", tags=["worker"])
AuthenticatedContext = Annotated[AccountRequestContext, Depends(get_authenticated_context)]


@dataclass(frozen=True)
class JobApiContext:
    """请求依赖对象；身份来源与数据库/路径由服务端明确装配。

    Attributes:
        account: 第 6 张已认证上下文，含唯一请求时刻和审计来源。
        service: 应用私有 JobService，不创建线程或缓存权限。
        paths: 应用显式状态路径，只允许日志尾读。
        scheduling: 必填关键字，应用只读调度服务；确实尚未配置时显式 None，调度接口报依赖不可用。
    """

    account: AccountRequestContext
    service: JobService
    paths: StatePaths
    scheduling: SchedulingService | None = dataclass_field(kw_only=True)


def configure_jobs(
    app: FastAPI,
    paths: StatePaths,
    registry: JobRegistry,
    *,
    scheduling: SchedulingCatalog,
) -> None:
    """给已配置数据库的 Web 应用绑定作业依赖。

    Args:
        app: create_app 返回的应用，database 非空且已迁移。
        paths: 显式配置的状态目录布局，不访问真实默认 home。
        registry: Web 入口构造的 production_registry 或测试登记对象。
        scheduling: 必填关键字，Web 入口提供的有效资源配置、定时登记和本地时区；
            无卡/无定时规则须提供相应空集合，不能省略或传 None 伪造未装配。

    Returns:
        无；应用 state 持有作业服务与路径，离线 OpenAPI 导出不需要调用。

    Raises:
        ExternalError: 应用没有数据库，不能假装提供业务服务。
        DefectError: 装配类型非法、路径与数据库不匹配或重复覆盖运行中服务。

    Side Effects:
        只修改 app.state，绑定 SchedulingService，Web 不自己读配置或构造资源池。
        不迁移、不初始化目录、不启动 worker、不修改已注册路径。

    Time Semantics:
        启动接收请求前调用一次，不读墙钟，无等待。
    """
    # 待实现：绑定入口显式提供的 SchedulingCatalog 和只读服务。
    engine = getattr(app.state, "database_engine", None)
    if engine is None:
        failure = _unavailable()
        raise failure
    if (
        not isinstance(engine, Engine)
        or not isinstance(cast(object, paths), StatePaths)
        or not isinstance(cast(object, registry), JobRegistry)
    ):
        raise DefectError()
    if (
        app.middleware_stack is not None
        or getattr(app.state, "job_service", None) is not None
        or Path(engine.url.database or "") != paths.database
    ):
        raise DefectError()
    app.state.job_service = JobService(engine, registry)
    app.state.job_paths = paths


def get_job_context(request: Request, account: AuthenticatedContext) -> JobApiContext:
    """取得已认证请求和显式装配的作业依赖。

    Args:
        request: 当前请求，只读 app.state，不接收路径或身份声明。
        account: get_authenticated_context 的结果，包含服务端时刻和 request_audit_context。

    Returns:
        当前请求 JobApiContext，普通成员与管理员相同。

    Raises:
        AuthenticationError: 未登录，401 并清 cookie。
        AuthorizationError: 写请求 Origin 不合法，403，先于认证和参数。
        PasswordChangeRequiredError: 必须改口令，403。
        ExternalError: 作业服务未配置，502。
        DefectError: 依赖或时钟损坏，500。

    Side Effects:
        仅复用全局鉴权结果，身份刷新沿用第 6 张，不额外读 cookie、记录载荷或创建服务。

    Time Semantics:
        每请求复用一个 UTC 时刻；不因轮询重置作业计时。
    """
    # 待实现：从应用状态补齐 scheduling 服务，禁止在请求内读配置或创建资源池。
    service, paths = (
        getattr(request.app.state, "job_service", None),
        getattr(request.app.state, "job_paths", None),
    )
    if service is None or paths is None:
        failure = _unavailable()
        raise failure
    if not isinstance(service, JobService) or not isinstance(paths, StatePaths):
        raise DefectError()
    return JobApiContext(account, service, paths, scheduling=None)


JobContext = Annotated[JobApiContext, Depends(get_job_context)]


@router.get("", response_model=JobListResponse, operation_id="list_jobs")
def list_jobs(context: JobContext, filters: Annotated[JobFilters, Query()]) -> JobListResponse:
    """返回按状态筛选、按自增编号倒序的作业游标页。

    Args:
        context: 已认证作业上下文，允许所有登录账号。
        filters: 状态、绑定游标及 1-100 的 limit，不接收操作者筛选以限制权限。

    Returns:
        HTTP 200 倒序页，编号为文本，UTC 微秒，末页 next_cursor=null。

    Raises:
        JobInputError: 筛选/游标非法，422；不回退查全部。
        AuthenticationError: 领域重验失败，401。
        PasswordChangeRequiredError: 强制改密，403。
        InputError: 数据库损坏，400。
        ConflictError: 读取锁冲突，409。
        ExternalError: 查询失败，502。
        DefectError: 转换或时钟错误，500；状态码以规范 6.2 为准。

    Side Effects:
        只读作业及当前页账号存在性，不读取作业日志，不记查看操作日志。

    Time Semantics:
        单次读锁最多 BUSY_TIMEOUT_MS；轮询由前端每秒发起，接口无等待循环。
    """
    page = context.service.list(
        _request(context), JobQuery(filters.state, filters.cursor, filters.limit)
    )
    return JobListResponse(
        items=tuple(_response(record) for record in page.items), next_cursor=page.next_cursor
    )


@router.post("", response_model=JobResponse, status_code=201, operation_id="submit_job")
def submit_job(context: JobContext, body: SubmitJobPayload) -> JobResponse:
    """提交登记类型并原子写操作日志。

    Args:
        context: 通过全局 Origin/登录/改密检查的上下文，审计来源必填。
        body: 稳定类型键及无秘密 JSON 参数，领域按对应模型校验。

    Returns:
        HTTP 201，新 queued 记录；事务提交后才响应，不等待 worker 在线。

    Raises:
        JobInputError: 未登记类型或模型/容量校验失败，422，不回显值。
        AuthenticationError: 写事务内会话失效，401。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 数据库损坏，400。
        ConflictError: 写入竞争/编号耗尽，409。
        ExternalError: 作业/日志事务失败，502。
        DefectError: 上下文/时钟/响应错误，500；统一处理器报告审计补记失败。

    Side Effects:
        新作业和提交操作日志同事务；参数不进审计明细，不在 Web 执行类型函数。

    Time Semantics:
        一次请求唯一 UTC 时刻；普通写锁预算 5 秒、失败补记 100 毫秒，不重试 POST。
    """
    return _response(
        context.service.submit(_request(context), body.type_name, dict(body.parameters))
    )


@router.post(
    "/example", response_model=JobResponse, status_code=201, operation_id="submit_count_job"
)
def submit_count_job(context: JobContext, body: CountParameters) -> JobResponse:
    """以类型化参数提交“示例：数数”，供表单和 OpenAPI 共同使用。

    Args:
        context: 任意登录且完成改密账号，同源写请求上下文。
        body: 严格步数、毫秒间隔、失败/警告序号及可选整体中止步。

    Returns:
        HTTP 201，type_name=example_count 的新 queued 记录。

    Raises:
        JobInputError: 示例范围或交叉字段非法，422；框架模型错误同样为安全 422。
        AuthenticationError: 会话无效，401。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 数据库损坏，400。
        ConflictError: 提交锁/约束冲突，409。
        ExternalError: 持久化失败，502。
        DefectError: 示例未正确登记或安全响应映射失败，500。

    Side Effects:
        委托 JobService.submit，与通用提交同一事务和审计规则；无导航层或数据访问。

    Time Semantics:
        body.interval_ms 只影响后台执行，不在 HTTP 里 sleep；锁和补记预算与提交一致。
    """
    record = context.service.submit(
        _request(context), "example_count", body.model_dump(mode="json")
    )
    return _response(record)


@router.post(
    "/example/gpu", response_model=JobResponse, status_code=201, operation_id="submit_gpu_job"
)
def submit_gpu_job(context: JobContext, body: GpuExampleParameters) -> JobResponse:
    """提交示例占卡作业，不在请求进程访问 GPU。

    Args:
        context: 完成全局 Origin/认证/改密检查的当前账号上下文。
        body: 占用秒数 0 至 GPU_EXAMPLE_MAX_HOLD_S，不接受卡号或命令路径。

    Returns:
        HTTP 201，新 example_gpu queued 记录；提交人是当前账号。

    Raises:
        JobInputError: 占用时长非法或类型未登记，422。
        AuthenticationError: 会话无效，401。
        PasswordChangeRequiredError: 必须改口令，403。
        ConflictError: 提交/审计事务竞争，409。
        InputError: 数据库损坏，400。
        ExternalError: 持久化失败，502。
        DefectError: 装配、时钟或响应映射错误，500；状态码以规范 6.2 为准。

    Side Effects:
        调 JobService.submit，共享提交审计和参数校验；无 nvidia-smi 子进程或资源预留。

    Time Semantics:
        用请求唯一 UTC 时刻，普通写锁 5 秒；执行时长只作用于 worker，不在 HTTP 等待。
    """
    raise NotImplementedError


@router.post(
    "/example/navigation",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_navigation_job",
)
def submit_navigation_job(context: JobContext, body: NavigationExampleParameters) -> JobResponse:
    """提交带预览期望值的写锁演示，不在 Web 核对或写示例文件。

    Args:
        context: 任意已登录且完成改密的账号与审计来源，Origin 已通过全局检查。
        body: 期望字符串 0-256 码点、锁内暂停 0-10 秒，拒绝文件路径和操作者声明。

    Returns:
        HTTP 201，新 example_navigation queued 记录；期待值是否匹配交 worker 锁内核对。

    Raises:
        JobInputError: 参数不合格或类型未登记，422；不以当前文件状态拒绝提交。
        AuthenticationError: 事务内身份失效，401。
        PasswordChangeRequiredError: 账号须改口令，403。
        ConflictError: 提交写锁/约束冲突，409。
        InputError: 数据库损坏，400。
        ExternalError: 新作业或审计事务失败，502。
        DefectError: 类型/时钟/响应转换缺陷，500。

    Side Effects:
        仅经 JobService.submit 新增作业及操作日志；不读取导航层、数据盘或示例文件，不持写锁。

    Time Semantics:
        本请求单次普通事务，无重试；pause_s 在后台持锁阶段才生效。
    """
    raise NotImplementedError


@router.get("/{job_id}", response_model=JobResponse, operation_id="get_job")
def get_job(context: JobContext, job_id: str) -> JobResponse:
    """读取任意作业详情和历史提交人。

    Args:
        context: 已认证上下文，不要求管理员或原提交人。
        job_id: 规范正整数十进制文本，最大 2^63-1，转换前校验。

    Returns:
        HTTP 200；未知进度总数为 null，取消/中断无 outcome，已删账号名字快照仍保留。

    Raises:
        JobInputError: 编号非法，422。
        JobNotFoundError: 编号不存在，404。
        AuthenticationError: 重验身份失败，401。
        PasswordChangeRequiredError: 须改密，403。
        InputError: 数据库损坏，400。
        ConflictError: 读取冲突，409。
        ExternalError: 查询失败，502。
        DefectError: 状态/结果映射错误，500。

    Side Effects:
        只读记录和账号存在性；不把日志文件全量装进响应。

    Time Semantics:
        UTC 微秒输出，浏览器转本地；单次普通读锁预算，无重试。
    """
    return _response(context.service.get(_request(context), _identifier(job_id)))


@router.post("/{job_id}/cancel", response_model=JobResponse, operation_id="cancel_job")
def cancel_job(context: JobContext, job_id: str) -> JobResponse:
    """由当前账号请求取消并返回已提交状态。

    Args:
        context: 同源 Origin 已检查的登录账号上下文。
        job_id: 规范正整数十进制文本，不按账号归属过滤。

    Returns:
        HTTP 200，排队作业已取消或运行作业正在取消，绝不声称外部工具已经退出。

    Raises:
        JobInputError: 编号不合法，422。
        JobNotFoundError: 编号不存在，404。
        ConflictError: 已正在取消/终态、条件更新冲突或写锁失败，409；执行前冲突不记日志。
        AuthenticationError: 会话失效，401。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 数据库损坏，400。
        ExternalError: 状态/审计事务失败，502。
        DefectError: 上下文或转换缺陷，500。

    Side Effects:
        状态在BEGIN IMMEDIATE内读取，worker先领取则本次转正在取消；状态与日志同事务，取消人是当前账号，不发送OS信号或删除产物。

    Time Semantics:
        最多普通 5 秒锁等待，补记最多 100 毫秒；worker 下次轮询才传播运行中取消。
    """
    return _response(context.service.cancel(_request(context), _identifier(job_id)))


@router.post(
    "/{job_id}/resubmit", response_model=JobResponse, status_code=201, operation_id="resubmit_job"
)
def resubmit_job(context: JobContext, job_id: str) -> JobResponse:
    """从终态记录新建作业，保留重新提交来源。

    Args:
        context: 当前点击按钮账号的认证及审计上下文，Origin 已检查。
        job_id: 原作业规范编号文本，只允许三个终态。

    Returns:
        HTTP 201，新编号、当前提交人、原参数及 resubmitted_from；原记录完全不变。

    Raises:
        JobInputError: 编号非法或类型/旧参数按当前版本不兼容，422。
        JobNotFoundError: 原作业不存在，404。
        ConflictError: 原作业非终态或提交竞争，409。
        AuthenticationError: 当前身份无效，401。
        PasswordChangeRequiredError: 强制改密，403。
        InputError: 数据库损坏，400。
        ExternalError: 新记录或审计提交失败，502。
        DefectError: 时间、上下文或响应映射错误，500。

    Side Effects:
        同事务新建作业与提交操作日志，明细带重新提交自，不修改原计数/状态或复制原提交人。

    Time Semantics:
        新提交采用请求 UTC 时刻，不继承旧起止时间；不等待 worker 运行，无自动重试。
    """
    return _response(context.service.resubmit(_request(context), _identifier(job_id)))


@router.get("/{job_id}/log", response_model=JobLogResponse, operation_id="get_job_log")
def get_job_log(context: JobContext, job_id: str) -> JobLogResponse:
    """读取指定作业的有界日志尾部。

    Args:
        context: 登录账号及可信状态目录；不得从请求接收文件路径。
        job_id: 正整数十进制文本，通过记录取得 log_path。

    Returns:
        HTTP 200，available/not_started/cleared 及最后至多 50 行；文件已清除不是 500。

    Raises:
        JobInputError: 编号非法，422。
        JobNotFoundError: 作业不存在，404。
        AuthenticationError: 会话失效，401。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 记录或数据库损坏，400。
        ConflictError: 查询锁冲突，409。
        ExternalError: 权限或文件/数据库 I/O 失败，502。
        DefectError: 路径越界、非普通文件或响应构造错误，500。

    Side Effects:
        先完成只读查询，再读 logs 内最多 64 KiB；不在文件 I/O 期间持数据库事务。

    Time Semantics:
        返回当次末尾完整行，终态后页面停止轮询；不等待新输出或锁住 worker。
    """
    record = context.service.get(_request(context), _identifier(job_id))
    return JobLogResponse(tail=read_log_tail(context.paths, record.log_path))


@worker_router.get("/status", response_model=WorkerStatusResponse, operation_id="get_worker_status")
def get_worker_status(context: JobContext) -> WorkerStatusResponse:
    """向全部登录账号提供 worker 在线判定。

    Args:
        context: 已认证请求上下文，以 account.now 计算心跳年龄。

    Returns:
        HTTP 200，超过 15 秒离线；无心跳也离线，未来心跳按零秒在线。

    Raises:
        AuthenticationError: 身份失效，401。
        PasswordChangeRequiredError: 强制改密，403。
        InputError: 数据库损坏，400。
        ConflictError: 读锁冲突，409。
        ExternalError: 心跳读取失败，502，不伪装离线。
        DefectError: 时钟、心跳或映射非法，500。

    Side Effects:
        只读单行心跳；不探测进程、不获取 worker 锁、不写操作日志。

    Time Semantics:
        UTC 跨进程比较，响应含 checked_at；每秒轮询由全局登录布局发起。
    """
    heartbeat = context.service.heartbeat(_request(context))
    return WorkerStatusResponse(
        online=heartbeat_online(heartbeat, now=context.account.now),
        instance_id=None if heartbeat is None else heartbeat.instance_id,
        pid=None if heartbeat is None else heartbeat.pid,
        started_at=None if heartbeat is None else heartbeat.started_at,
        last_seen_at=None if heartbeat is None else heartbeat.last_seen_at,
        checked_at=context.account.now,
    )


def _request(context: JobApiContext) -> JobRequest:
    """复用已认证身份、请求唯一时刻与服务器审计来源，不另读cookie或时钟。"""
    account = context.account
    return JobRequest(identity(account), account.now, account.audit)


def _response(record: JobRecord) -> JobResponse:
    """在 HTTP 边界转换 64 位编号；系统账号编号保持 None，不输出字符串 None 或已删除标记。"""
    # 待实现：系统身份保留 null，资源新增字段由记录快照映射，不读 worker 内存。
    data = asdict(record)
    data["job_id"] = str(record.job_id)
    data["resubmitted_from"] = (
        None if record.resubmitted_from is None else str(record.resubmitted_from)
    )
    data["submitted_by"] = {
        "account_id": str(record.submitted_by.account_id),
        "name": record.submitted_by.name,
        "deleted": record.submitter_deleted,
    }
    for field in ("submitter_deleted", "artifacts", "tool_exit_code"):
        data.pop(field)
    return JobResponse.model_validate(data)


def _identifier(value: str) -> int:
    """先匹配规范文本再转整数，不接受前导零或浏览器已损失精度的浮点数。"""
    if re.fullmatch(r"[1-9][0-9]{0,18}", value) is None or int(value) > MAX_SQLITE_INTEGER:
        raise JobInputError(invalid_field("job_id", "1至2^63-1的规范十进制文本").diagnostics)
    return int(value)


def _unavailable() -> ExternalError:
    """未装配数据库/状态布局是依赖不可用，不伪装成空队列或worker离线。"""
    return ExternalError(
        (
            Diagnostic(
                level=DiagnosticLevel.ERROR,
                category=DiagnosticCategory.EXTERNAL,
                stage="作业接口",
                source="平台",
                objects=(),
                rule="作业服务必须完成入口装配",
                actual="作业服务尚未配置",
                expected="配置数据库、状态路径与类型登记",
                consequence="本次作业请求不能执行",
                next_step="检查Web入口的作业服务配置",
            ),
        )
    )


@worker_router.get("/scheduling", response_model=SchedulingResponse, operation_id="get_scheduling")
def get_scheduling(context: JobContext) -> SchedulingResponse:
    """向全部登录账号返回调度的数据库展示快照。

    Args:
        context: 全局认证得到的上下文，必须改密规则照旧；不要求管理员。

    Returns:
        HTTP 200，类型上限/数量、卡主、写锁持有人、每日下次时间及上次结果；编号文本、时刻 UTC。

    Raises:
        AuthenticationError: 未登录或会话重验失败，401。
        PasswordChangeRequiredError: 必须先改口令，403。
        InputError: 数据库/历史记录损坏，400。
        ConflictError: 快照读取锁竞争，409。
        ExternalError: 未注入调度配置或数据库不可读，502，不能伪装为空闲。
        DefectError: 资源副本矛盾、非法时钟或映射错误，500。

    Side Effects:
        只调用 SchedulingService.snapshot；不读配置文件、不探测 GPU、不调用 worker 内存或访问数据盘。
        全部路径走第 6 张全局鉴权，拒绝时先于业务查询；不记查看操作日志。

    Time Semantics:
        使用 account.now 的唯一 UTC 请求时刻；普通读锁 5 秒、无内部轮询，页面约每秒查询。
    """
    raise NotImplementedError
