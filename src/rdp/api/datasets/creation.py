"""建链与新增数据集 HTTP 入口（M1-08），成员与管理员均可用。

只调用 create_service 提交/查询，不导入 worker builder、执行器或写入流水线。
复用全局 Origin→认证→强制改密边界；声明的路由参与离线 OpenAPI 导出。
"""

from dataclasses import dataclass
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.datasets.creation_schemas import ConfirmCreationRequest, CreationSubmitResponse
from rdp.api.job_schemas import JobResponse
from rdp.jobs.navwrite.create_models import DatasetPreviewParameters, LinkPreviewParameters
from rdp.jobs.navwrite.create_service import CreationAccess
from rdp.jobs.navwrite.create_views import CreationJobId, CreationOptions, CreationPreviewView

router = APIRouter(prefix="/api/datasets", tags=["dataset-creation"])


@dataclass(frozen=True)
class CreationApiContext:
    """本次创建请求的服务器上下文，不含导航或存储根访问器。

    Attributes:
        account: 已认证身份、唯一 UTC 时刻及来源 IP/请求编号。
        access: 从 app.state 中现有 database_engine、job_paths、job_service 构造的最小依赖。
    """

    account: AccountRequestContext
    access: CreationAccess


def get_creation_context(
    request: Request,
    account: Annotated[AccountRequestContext, Depends(get_authenticated_context)],
) -> CreationApiContext:
    """复用已有应用作业装配，取得创建接口的可信请求上下文。

    Args:
        request: 当前请求，只读取 app.state 中已装配对象，不发现默认配置或路径。
        account: 成员或管理员的认证结果；写请求 Origin 已由全局边界先行检查。

    Returns:
        CreationApiContext；身份和审计字段不得使用默认值或客户端声明。

    Raises:
        AuthenticationError: 无有效会话，401。
        AuthorizationError: 写请求 Origin 缺失或非本站，403。
        PasswordChangeRequiredError: 账号必须改密，403。
        ExternalError: 数据库、作业服务或状态路径未装配，502。
        DefectError: 对象类型或引擎不一致，500。

    Side Effects:
        只读取应用内存装配；会话活动刷新沿用现有安全边界，不读取任何导航文件。

    Time Semantics:
        复用 account.now；无锁等待、目标检查或后台任务。
    """
    raise NotImplementedError


CreationContext = Annotated[CreationApiContext, Depends(get_creation_context)]


@router.get(
    "/creation-options", response_model=CreationOptions, operation_id="get_dataset_creation_options"
)
def get_creation_options(context: CreationContext) -> CreationOptions:
    """返回创建表单的格式和数据来源候选。

    Args:
        context: 当前账号和最小查询依赖，无管理员限制。

    Returns:
        200，formats 含登记目录、版本层标记与索引版本候选；data_origins 为全部合法中文值。

    Raises:
        AuthenticationError: 会话失效，401。
        PasswordChangeRequiredError: 未完成改密，403。
        InputError: 版本索引损坏，400。
        ConflictError: 候选查询竞争，409。
        ExternalError: 候选读取或装配失败，502。
        DefectError: 依赖、时刻或展示映射违约，500。

    Side Effects:
        仅调用 read_creation_options 查询索引与登记规则，不扫描存储或导航目录。

    Time Semantics:
        同步短查询，数据库预算沿用 M0；前端离页清理缓存，不轮询候选。
    """
    raise NotImplementedError


@router.post(
    "/link-previews",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_dataset_link_preview",
)
def submit_link_preview(context: CreationContext, body: LinkPreviewParameters) -> JobResponse:
    """提交建链预览，目标检查交给 worker。

    Args:
        context: 服务器认证身份、UTC 时刻和审计上下文。
        body: dataset_id、link{name,target_path,fallback_format}、format_entries[{format,version}]。
            非法名称/额外字段按统一 422 拒绝，不回显不可信值。

    Returns:
        201，nav_create_link_preview 的完整 M0 queued 记录；不等待预览完成。

    Raises:
        DatasetNotFoundError: 编号未入索引，404。
        JobInputError: 未登记、参数或去重/编码预算校验失败，422。
        AuthenticationError: 提交事务内会话失效，401。
        AuthorizationError: Origin 非本站，403，先于 body 校验。
        PasswordChangeRequiredError: 强制改密，403。
        InputError: 索引或作业数据损坏，400。
        ConflictError: 提交竞争或编号耗尽，409。
        ExternalError: 队列与提交日志持久化失败，502。
        DefectError: 提交装配或响应映射错误，500。

    Side Effects:
        调用领域 submit_link_preview，再用 M0 作业响应转换；只新增作业与提交日志。
        不打开目标、不运行 builder、不拿导航写锁。

    Time Semantics:
        使用请求唯一提交时刻；客户端按 JOB_POLL_INTERVAL_MS 轮询作业状态，无 POST 重试。
    """
    raise NotImplementedError


@router.post(
    "/creation-previews",
    response_model=JobResponse,
    status_code=201,
    operation_id="submit_dataset_creation_preview",
)
def submit_dataset_preview(context: CreationContext, body: DatasetPreviewParameters) -> JobResponse:
    """提交新增数据集预览，由 worker 计算预计编号和入口差异。

    Args:
        context: 当前成员/管理员的会话及服务端审计来源。
        body: dataset_name、data_origin、link 和 format_entries；来源必填，编号不允许传入。

    Returns:
        201，nav_create_dataset_preview 的 M0 queued 记录；编号只在成功预览中展示。

    Raises:
        JobInputError: 名称/来源/格式选择不合法、超预算或类型未登记，422。
        AuthenticationError: 当前会话在写事务内失效，401。
        AuthorizationError: Origin 检查失败，403。
        PasswordChangeRequiredError: 当前账号必须改密，403。
        InputError: 已有作业数据损坏，400。
        ConflictError: 提交/日志竞争，409。
        ExternalError: 队列数据库写失败，502。
        DefectError: 时钟或参数/响应映射违约，500。

    Side Effects:
        新增只读预览作业及提交日志；不建目录、不分配编号、不创建来源文件。

    Time Semantics:
        排队立即返回；HTTP 超时不证明提交失败，页面不盲目重发。
    """
    raise NotImplementedError


@router.get(
    "/creation-previews/{preview_job_id}",
    response_model=CreationPreviewView,
    operation_id="get_dataset_creation_preview",
)
def get_creation_preview(
    context: CreationContext, preview_job_id: CreationJobId
) -> CreationPreviewView:
    """读取任一种成功创建预览供页面确认。

    Args:
        context: 当前登录账号与只读状态目录依赖。
        preview_job_id: 规范十进制文本，1 至 MAX_SQLITE_INTEGER；始终以文本传给前端。

    Returns:
        200，预览身份、UTC 时刻、操作、参数、PlanReport 和当前 queued_jobs；
        report.creation 明确列文件/链接/数据块/根及按格式入口，不传完整执行计划。

    Raises:
        JobNotFoundError: 作业编号不存在，404。
        JobInputError: 编号超范围，422。
        AuthenticationError: 读取时账号会话失效，401。
        PasswordChangeRequiredError: 须先改密，403。
        InputError: 未成功完成、错误类型、文件过期/丢失/损坏或关联不合法，400。
        ConflictError: 读取队列竞争，409。
        ExternalError: 状态文件、数据库读取失败，502。
        DefectError: 报告与计划不一致或创建差异缺失，500。

    Side Effects:
        仅调用 read_creation_preview，查询数据库并读取已存预览文件；不访问导航或目标。

    Time Semantics:
        created_at 不刷新；预览沿用七天保留期，过期提示重新预览；不等待运行中的预览结束。
    """
    raise NotImplementedError


@router.post(
    "/creation-writes",
    response_model=CreationSubmitResponse,
    operation_id="confirm_dataset_creation_write",
)
def confirm_creation_write(
    context: CreationContext, body: ConfirmCreationRequest
) -> CreationSubmitResponse:
    """确认保存的创建预览并提交通用写入作业，出现新排队提醒时要求再次确认。

    Args:
        context: 本次确认者身份，作业和操作日志用该身份而非预览作者。
        body: preview_job_id 与 acknowledged_queue_job_ids；不接受其他参数或 plan。

    Returns:
        200，confirmation_required=True 时 job=null、queued_jobs 非空，尚未提交；
        False 时 job 为已提交的 nav_write_apply 完整记录，parameters 只有整数 preview_job_id。

    Raises:
        JobNotFoundError: 预览作业不存在，404。
        JobInputError: 非法/重复编号、额外字段或类型未登记，422。
        AuthenticationError: 提交事务中确认者会话失效，401。
        AuthorizationError: 同源写请求检查失败，403。
        PasswordChangeRequiredError: 确认者必须先改密，403。
        InputError: 预览类型/成功状态/文件不合约，400。
        ConflictError: 提交事务竞争，409；实际导航冲突在写入作业诊断中展示。
        ExternalError: 读取预览或持久化作业/日志失败，502。
        DefectError: 领域结果或依赖违反契约，500。

    Side Effects:
        委托 submit_creation_write；提醒分支不提交，正常分支只写作业及提交日志，
        HTTP 不执行计划。恢复失败时作业仍可排队，由既有门禁保护导航写入。

    Time Semantics:
        确认前刷新队列快照；作业入队后立即返回，页面转 /jobs/$jobId；不重试 POST。
        导航变化由 worker 在写锁内核对，冲突提示列出差异并要求重新预览。
    """
    raise NotImplementedError
