"""数据集HTTP入口（M1-03），统一使用Origin→认证→强制改密边界及五段诊断。

所有登录账号可用；路由只调用浏览服务，不访问存储根或调用作业执行函数。
模型由领域层提供单一定义，复用M0的作业响应和OpenAPI导出机制。
"""

import logging
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Query, Request
from fastapi.responses import PlainTextResponse, Response

from rdp.api._account_context import identity
from rdp.api._job_views import response as _job_response
from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.job_schemas import JobResponse
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import DefectError, DiagnosticCategory, ExternalError
from rdp.jobs.dataset_browser.schemas import (
    DatasetDetailResponse,
    DatasetFilterOptions,
    DatasetFilters,
    DatasetId,
    DatasetListQuery,
    DatasetListResponse,
    DatasetPanelResponse,
    DatasetTreesResponse,
    EntryPath,
    LayoutRequest,
    LayoutResponse,
)
from rdp.jobs.dataset_browser.service import DatasetBrowserService
from rdp.jobs.datasets.sizing import SizingParameters
from rdp.jobs.service import JobRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/datasets", tags=["datasets"])


@dataclass(frozen=True)
class DatasetApiContext:
    """HTTP请求的已认证上下文，不存Session、文件句柄或存储根访问器。

    Attributes:
        account: M0全局认证结果，含唯一UTC时刻、当前身份和审计来源。
        service: 启动期显式装配的浏览服务，生命周期由入口管理。
    """

    account: AccountRequestContext
    service: DatasetBrowserService


def configure_datasets(app: FastAPI, service: DatasetBrowserService) -> None:
    """为应用绑定数据集浏览服务，不激活迁移或加载导航内容。

    Args:
        app: 尚未启动的create_app应用，路由与全局安全边界已登记。
        service: 显式数据库、导航根、作业服务及型号读取器构造的浏览服务。

    Returns:
        无；app.state.dataset_browser_service保存该服务，离线导出不需要调用。

    Raises:
        DefectError: 应用已启动、服务类型错误或重复配置。

    Side Effects:
        只改应用内存装配；不连接数据库、不发现默认路径、不检查存储挂载。

    Time Semantics:
        在接受请求前调用一次，无时钟、等待或重试。
    """
    if app.middleware_stack is not None or hasattr(app.state, "dataset_browser_service"):
        raise DefectError()
    app.state.dataset_browser_service = service


def get_dataset_context(
    request: Request,
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
) -> DatasetApiContext:
    """取得数据集服务及复用全局认证的当前身份。

    Args:
        request: 当前受保护请求，读取应用服务，不接收客户端路径配置。
        account: M0安全依赖验证的身份及唯一时刻；所有成员均可访问。

    Returns:
        本请求的DatasetApiContext；OpenAPI通过依赖声明SessionCookie。

    Raises:
        AuthenticationError: 无有效登录，401并清cookie。
        AuthorizationError: 写请求Origin无效，403；全局边界先于请求体解析检查。
        PasswordChangeRequiredError: 当前账号必须先改密，403。
        ExternalError: 浏览服务尚未配置，502，不冒充空索引。
        DefectError: 已配置对象类型不正确，500；其余认证异常由M0边界处理。

    Side Effects:
        只读取全局认证结果和应用服务；认证活动刷新沿用M0独立短事务，无业务查询。

    Time Semantics:
        复用account.now，不重新读时钟或延长会话；身份先于路由参数校验。
    """
    service = getattr(request.app.state, "dataset_browser_service", None)
    if service is None:
        raise ExternalError(
            tuple(
                item.model_copy(update={"category": DiagnosticCategory.EXTERNAL})
                for item in invalid_field("datasets", "浏览服务必须配置").diagnostics
            )
        )
    if not isinstance(service, DatasetBrowserService):
        raise DefectError()
    return DatasetApiContext(account, service)


DatasetContext = Annotated[DatasetApiContext, Depends(get_dataset_context)]


@router.get("/trees", response_model=DatasetTreesResponse, operation_id="get_dataset_trees")
def get_dataset_trees(
    context: DatasetContext, filters: Annotated[DatasetFilters, Query()]
) -> DatasetTreesResponse:
    """返回共用筛选条件的按任务/按格式两棵树。

    Args:
        context: 当前已登录且完成改密的账号及浏览服务。
        filters: 型号、原标签、整数FPS/unknown、来源和视图路径筛选；未提供表示不限。

    Returns:
        200，nodes平铺节点及indexed_at；每节点含数量、大小来源计数和原统计时间范围。

    Raises:
        DatasetQueryError: 路径、FPS或筛选组合非法，422。
        InputError: 索引损坏或树超过扫描预算，400。
        AuthenticationError: 读事务重验失败，401。
        PasswordChangeRequiredError: 账号须改密，403。
        ConflictError: 树读取锁超时，409。
        ExternalError: 数据库或型号目录不可读，502。
        DefectError: 聚合或响应模型非法，500；状态映射以规范6.2为准。

    Side Effects:
        只调用service.trees，不读导航或挂载表，不在请求中测量大小。

    Time Semantics:
        同步查询在工作线程；单次事务快照，数据库等待使用BUSY_TIMEOUT_MS。
    """
    return context.service.trees(_request(context), filters)


@router.get("", response_model=DatasetListResponse, operation_id="list_datasets")
def list_datasets(
    context: DatasetContext, query: Annotated[DatasetListQuery, Query()]
) -> DatasetListResponse:
    """返回按名称排序的筛选数据集页及损坏入口占位。

    Args:
        context: 当前认证上下文，无管理员额外限制。
        query: 共享筛选加offset和limit，默认0及100，单页1至100项。

    Returns:
        200，items/total/offset/limit/indexed_at；同编号去重，entries提供全部跨视图跳转位置。

    Raises:
        DatasetQueryError: 分页/筛选不合法，422，不静默忽略条件。
        InputError: 索引数据不能解码，400。
        AuthenticationError: 当前会话失效，401。
        PasswordChangeRequiredError: 强制改密，403。
        ConflictError: 列表事务竞争，409。
        ExternalError: 数据或映射查询失败，502。
        DefectError: 型号多重对应或序列化违约，500。

    Side Effects:
        只查索引；不把14项或子任务全文塞入列表，不更新索引。

    Time Semantics:
        每页内部一致，跨页可受新扫描影响；返回实际索引时间，不生成假刷新时刻。
    """
    return context.service.list(_request(context), query)


@router.get("/filters", response_model=DatasetFilterOptions, operation_id="get_dataset_filters")
def get_dataset_filters(context: DatasetContext) -> DatasetFilterOptions:
    """返回筛选选项及型号空目录时的前端降级提示。

    Args:
        context: 全局安全检查通过的账号上下文与浏览服务。

    Returns:
        200，robot_models_registered、default_robot_filter及型号/标签/FPS/来源候选。
        空目录默认robot_type，登记后默认robot_model；每类unknown项独立且保留零计数。

    Raises:
        AuthenticationError: 查询阶段会话失效，401。
        PasswordChangeRequiredError: 必须改密，403。
        InputError: 元信息索引损坏，400。
        ConflictError: 候选读取竞争，409。
        ExternalError: 型号读取器或数据库失败，502。
        DefectError: 型号重复、响应形状非法，500。

    Side Effects:
        只读全索引候选及型号投影；不读取meta文件、不登记新型号。

    Time Semantics:
        每次请求读取最新已提交目录，不缓存空型号表；无轮询等待。
    """
    return context.service.filter_options(_request(context))


@router.get("/panel", response_model=DatasetPanelResponse, operation_id="get_dataset_panel")
def get_dataset_panel(
    context: DatasetContext, dataset_id: Annotated[DatasetId | None, Query()] = None
) -> DatasetPanelResponse:
    """返回一致性面板发现与存储根顶部提示。

    Args:
        context: 当前账号上下文；成员与管理员得到相同数据范围。
        dataset_id: 可选永久编号；不传查全局，传入时只筛该数据集发现。

    Returns:
        200，findings四组两级聚合、storage_roots及indexed_at；样例有界、total完整。

    Raises:
        DatasetNotFoundError: 指定数据集未入索引，404。
        DatasetQueryError: 编号不合法，422。
        AuthenticationError: 查询时身份已失效，401。
        PasswordChangeRequiredError: 需要改口令，403。
        InputError: 已存诊断或根状态损坏，400。
        ConflictError: 面板读锁超时，409。
        ExternalError: 面板查询失败，502。
        DefectError: 五段诊断展示映射错误，500。

    Side Effects:
        仅查询扫描发现，离线提示不触发实时探测，不写修复或重扫作业。

    Time Semantics:
        根状态保留上次checked_at；未检查为null，不能声称本请求验证了存储可用性。
    """
    return context.service.panel(_request(context), dataset_id)


@router.get("/detail", response_model=DatasetDetailResponse, operation_id="get_dataset_detail")
def get_dataset_detail(
    context: DatasetContext, entry_path: Annotated[EntryPath, Query()]
) -> DatasetDetailResponse:
    """读取所选入口原文及规范信息，独立返回推导值和索引过期标记。

    Args:
        context: 当前账号、服务端UTC时刻及受限导航读取服务。
        entry_path: 树/列表返回的相对入口路径；先查索引再打开，不接受任意绝对路径。

    Returns:
        200，原始路径与信息原文、规范信息、推导数据块、索引链接/大小和index_stale；
        子任务仅提供subtasks_entry_path，未知身份入口同样可按位置查看。

    Raises:
        DatasetNotFoundError: 入口不在索引，404。
        DatasetQueryError: 路径穿越或参数非法，422。
        AuthenticationError: 会话失效，401。
        PasswordChangeRequiredError: 须改密，403。
        InputError: 索引损坏或整体导航预算超限，400。
        ConflictError: 索引查询锁超时，409。
        ExternalError: 数据库或导航根整体不可读，502；单文件失败以诊断局部返回。
        DefectError: 推导或响应字段错误，500。

    Side Effects:
        只读导航普通文件和链接自身；不跟随存储目标，不修改索引，不隐藏坏JSON原文。

    Time Semantics:
        SQL完成后再读文件；L12比较使用内容指纹，不用mtime，漂移时保守标过期。
    """
    started = time.monotonic()
    result = context.service.detail(_request(context), entry_path)
    # 只在HTTP边界记录规模和单调耗时，不记录导航JSON正文或重复下层错误。
    logger.debug(
        "数据集详情读取完成",
        extra={
            "fields": {
                "entry_path": entry_path,
                "index_stale": result.index_stale,
                "source_count": len(result.sources),
                "elapsed_s": max(0.0, time.monotonic() - started),
            }
        },
    )
    return result


@router.get(
    "/subtasks",
    response_class=PlainTextResponse,
    operation_id="get_dataset_subtasks",
    responses={
        200: {
            "description": "子任务.json原始UTF-8字节；用parseAs=text交工作线程解析，不包装JSON字符串",
            "headers": {
                "X-Index-Stale": {"schema": {"type": "string", "enum": ["true", "false"]}},
                "X-Document-SHA256": {"schema": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
                "X-Observed-At": {"schema": {"type": "string", "format": "date-time"}},
                "Cache-Control": {"schema": {"type": "string", "enum": ["no-store"]}},
                "X-Content-Type-Options": {"schema": {"type": "string", "enum": ["nosniff"]}},
                "Content-Length": {"schema": {"type": "string", "pattern": "^[0-9]+$"}},
            },
        }
    },
)
def get_dataset_subtasks(
    context: DatasetContext, entry_path: Annotated[EntryPath, Query()]
) -> Response:
    """单独返回大子任务文件原文，避免主详情响应和主线程JSON解析负担。

    Args:
        context: 已认证且完成改密的请求，文件服务只持有导航根。
        entry_path: 已索引入口的相对路径；文件名固定，前端无需拼接文件系统绝对路径。

    Returns:
        200 text/plain; charset=utf-8，原始字节、不做JSON编码；Content-Length为原字节数。
        X-Index-Stale是true/false，X-Document-SHA256对应发送内容，X-Observed-At为UTC；
        Cache-Control=no-store，X-Content-Type-Options=nosniff。失败仍是application/problem+json。

    Raises:
        DatasetNotFoundError: 入口未入索引，404。
        DatasetQueryError: 相对路径非法，422。
        AuthenticationError: 读取前会话无效，401。
        PasswordChangeRequiredError: 账号须改密，403。
        InputError: 文件缺失、非普通文件、非UTF-8或超过32MiB，400。
        ConflictError: 数据库忙或读取期间文件变化，409；不发送半份正文。
        ExternalError: 导航权限/I/O或索引失败，502。
        DefectError: 摘要与响应构造违约，500。

    Side Effects:
        同步服务先完整受限读取，再以Response发送现成bytes；不用按路径重开文件的FileResponse。
        不缓存全文、不写临时文件、不访问链接目标、不在Web执行后台解析或统计作业。

    Time Semantics:
        约14MB受已有32MiB预算覆盖，读取在工作线程；响应发送交ASGI，无自动重试或压缩。
        网络断开只终止发送，不改变已读文件；真实响应时间由工单验收1的只读演练测量。
    """
    started = time.monotonic()
    document = context.service.subtasks(_request(context), entry_path)
    logger.debug(
        "子任务原文读取完成",
        extra={
            "fields": {
                "entry_path": entry_path,
                "size_bytes": len(document.content),
                "index_stale": document.index_stale,
                "elapsed_s": max(0.0, time.monotonic() - started),
            }
        },
    )
    return Response(
        document.content,
        media_type="text/plain; charset=utf-8",
        headers={
            "X-Index-Stale": str(document.index_stale).lower(),
            "X-Document-SHA256": document.sha256,
            "X-Observed-At": document.observed_at.isoformat(),
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post(
    "/sizing", response_model=JobResponse, status_code=201, operation_id="submit_dataset_sizing"
)
def submit_dataset_sizing(context: DatasetContext, body: SizingParameters) -> JobResponse:
    """按当前账号提交一次全量或单数据集统计大小作业。

    Args:
        context: Origin、认证及强制改密已经通过的上下文，审计来源来自服务器。
        body: 正式SizingParameters，dataset_id省略或null为全量；不接受存储根、提交人或类型覆盖。

    Returns:
        201，复用M0完整JobResponse，新作业queued，type_name=dataset_sizing。

    Raises:
        DatasetNotFoundError: 指定编号不存在，404。
        DatasetQueryError: 编号不合约，422。
        JobInputError: 类型未登记或参数不兼容，422。
        AuthenticationError: 提交事务内身份失效，401。
        AuthorizationError: Origin缺失或非本站，403，在读取body前拒绝。
        PasswordChangeRequiredError: 账号须改密，403。
        InputError: 数据库损坏，400。
        ConflictError: 作业或审计写入竞争，409。
        ExternalError: 持久化失败，502。
        DefectError: 提交装配或M0响应映射错误，500。

    Side Effects:
        只提交作业并写M0提交日志；复用第02张参数模型，不调用统计执行器、不更新大小。

    Time Semantics:
        使用请求唯一UTC提交时刻，不等待worker在线或执行；客户端不自动重试POST。
    """
    return _job_response(context.service.submit_sizing(_request(context), body.dataset_id))


@router.get("/layout", response_model=LayoutResponse, operation_id="get_dataset_layout")
def get_dataset_layout(context: DatasetContext) -> LayoutResponse:
    """读取当前账号跨会话保存的A/B/C布局。

    Args:
        context: 当前登录身份；不从请求接收其他账号编号。

    Returns:
        200，layout及updated_at；无偏好行时A和null。

    Raises:
        AuthenticationError: 未登录或领域重验失败，401。
        PasswordChangeRequiredError: 账号必须改密，403。
        InputError: 布局记录损坏，400。
        ConflictError: 偏好查询锁超时，409。
        ExternalError: 布局表未迁移或查询失败，502。
        DefectError: 响应或时刻非法，500。

    Side Effects:
        仅查询当前账号行；GET不创建默认偏好，不读导航层。

    Time Semantics:
        返回最后保存的UTC时刻，无保存记录时不使用当前时间冒充。
    """
    return context.service.get_layout(_request(context))


@router.put("/layout", response_model=LayoutResponse, operation_id="set_dataset_layout")
def set_dataset_layout(context: DatasetContext, body: LayoutRequest) -> LayoutResponse:
    """保存当前账号的布局，供其他会话及浏览器读取。

    Args:
        context: 已通过同源写请求检查的当前账号，事务内仍重验身份。
        body: 只有layout字段，严格A/B/C；拒绝account_id及额外字段。

    Returns:
        200，已提交布局和UTC修改时刻；重复保存相同值保持原时刻。

    Raises:
        DatasetQueryError: 布局非法，422；框架参数校验也使用统一422诊断。
        AuthenticationError: 未登录或事务重验失效，401。
        AuthorizationError: Origin不合格，403，先于body校验。
        PasswordChangeRequiredError: 当前账号须改密，403。
        InputError: 现有偏好或账号记录损坏，400。
        ConflictError: 写锁或约束冲突，409。
        ExternalError: 偏好事务失败，502，旧选择保留。
        DefectError: 审计上下文或响应映射错误，500。

    Side Effects:
        只提交当前账号一行偏好，不写操作日志；其他账号完全不变，不记录筛选状态。

    Time Semantics:
        最后提交者生效，同值不写；时钟回拨不降低updated_at，锁预算沿用M0。
    """
    return context.service.set_layout(_request(context), body.layout)


# 固定路径先声明，避免dataset_id捕获layout、panel等名字；新接口均在全局API兜底之前注册。
@router.post(
    "/{dataset_id}/rescan",
    response_model=JobResponse,
    status_code=201,
    operation_id="rescan_dataset",
)
def rescan_dataset(context: DatasetContext, dataset_id: DatasetId) -> JobResponse:
    """将链接状态旁的重新检查操作转换成单数据集扫描作业。

    Args:
        context: 当前登录且完成改密账号，Origin已由全局安全边界验证。
        dataset_id: 永久编号，1至256码点，不含分隔符、空白或NUL；不接受全量范围。

    Returns:
        201，M0 JobResponse，type_name=dataset_rescan，parameters仅dataset_id，提交人为当前账号。

    Raises:
        DatasetNotFoundError: 编号尚未入索引，404。
        DatasetQueryError: 编号不合约，422。
        JobInputError: 扫描类型未登记或参数模型不兼容，422。
        AuthenticationError: 提交时会话失效，401。
        AuthorizationError: 写请求Origin缺失/无效，403。
        PasswordChangeRequiredError: 账号须改密，403。
        InputError: 索引或作业数据损坏，400。
        ConflictError: 提交/日志写锁冲突，409。
        ExternalError: 作业持久化失败，502。
        DefectError: 登记或响应转换错误，500。

    Side Effects:
        JobService提交及审计同事务；Web不运行扫描、不持导航写锁，不立即重算链接状态。

    Time Semantics:
        提交后立即返回排队记录，前端按M0作业接口查询进度；不以HTTP请求超时取消作业。
    """
    return _job_response(context.service.submit_rescan(_request(context), dataset_id))


def _request(context: DatasetApiContext) -> JobRequest:
    """沿用服务器认证身份与同一次请求的时刻，不接受客户端操作者。"""
    account = context.account
    return JobRequest(identity(account), account.now, account.audit)
