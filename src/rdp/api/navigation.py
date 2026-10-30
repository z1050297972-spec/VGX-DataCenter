"""导航层恢复失败标记的 HTTP 入口（M1-07，ADR 0009）。

读：所有登录账号；确认：仅管理员（get_admin_context，角色检查先于参数）。
本模块只碰数据库和状态目录，不碰导航层；按 import-linter 合约，不 import atomic、recovery、pipeline、jobs。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Engine

from rdp.api._account_context import identity
from rdp.api.account_auth import (
    AccountRequestContext,
    get_admin_context,
    get_authenticated_context,
)
from rdp.api.navigation_schemas import (
    AcknowledgeResponse,
    MismatchItemResponse,
    RecoveryBlockResponse,
)
from rdp.infra.actors import ActorRef
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    ExternalError,
)
from rdp.infra.state import StatePaths
from rdp.jobs.navwrite.marker import (
    AcknowledgeRequest,
    acknowledge_recovery_block,
    read_recovery_block,
)

router = APIRouter(prefix="/api/navigation", tags=["navigation"])
AuthenticatedContext = Annotated[AccountRequestContext, Depends(get_authenticated_context)]
AdminContext = Annotated[AccountRequestContext, Depends(get_admin_context)]


def _dependencies(request: Request) -> tuple[Engine, StatePaths]:
    """取应用装配的数据库和状态布局；未装配是依赖不可用，不伪装成没有标记。"""
    engine = getattr(request.app.state, "database_engine", None)
    paths = getattr(request.app.state, "job_paths", None)
    if engine is None or paths is None:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="导航层恢复标记",
                    source="平台",
                    objects=(),
                    rule="恢复标记接口必须完成入口装配",
                    actual="数据库或状态目录尚未配置",
                    expected="配置数据库与状态路径",
                    consequence="本次请求不能执行",
                    next_step="检查Web入口的作业服务配置",
                ),
            )
        )
    if not isinstance(engine, Engine) or not isinstance(paths, StatePaths):
        raise DefectError()
    return engine, paths


@router.get(
    "/recovery-block",
    response_model=RecoveryBlockResponse,
    response_model_exclude_none=True,
    operation_id="get_navigation_recovery_block",
)
def get_recovery_block(request: Request, context: AuthenticatedContext) -> RecoveryBlockResponse:
    """读取“导航层恢复失败”标记，供所有页面顶部提示和详情页使用。

    Args:
        request: 当前请求，只读 app.state 的数据库装配。
        context: 全局认证上下文，成员与管理员相同。

    Returns:
        HTTP 200；没有标记时 {"blocked": false}，有标记时带 set_at、job_ids、items 样例和完整 total_items。

    Raises:
        AuthenticationError: 未登录，401。
        PasswordChangeRequiredError: 必须改口令，403。
        InputError: 标记行损坏，400。
        ConflictError: 只读锁冲突，409。
        ExternalError: 依赖未装配或读取失败，502。
        DefectError: 装配或转换缺陷，500。

    Side Effects:
        只读数据库；不读导航层，不写操作日志。

    Time Semantics:
        每次读取当前已提交状态，不缓存；前端约每秒轮询一次，接口无等待。
    """
    del context
    engine, _ = _dependencies(request)
    with session_scope(engine, read_only=True) as session:
        block = read_recovery_block(session)
    if block is None:
        return RecoveryBlockResponse(blocked=False)
    return RecoveryBlockResponse(
        blocked=True,
        set_at=block.set_at,
        job_ids=tuple(str(job_id) for job_id in block.job_ids),
        items=tuple(
            MismatchItemResponse(
                job_id=str(item.job_id),
                step_index=item.step_index,
                path=item.path,
                expected_before=item.expected_before,
                expected_after=item.expected_after,
                actual=item.actual,
            )
            for item in block.items
        ),
        total_items=block.total_items,
    )


@router.post(
    "/recovery-block/acknowledge",
    response_model=AcknowledgeResponse,
    operation_id="acknowledge_navigation_recovery_block",
)
def acknowledge_block(request: Request, context: AdminContext) -> AcknowledgeResponse:
    """管理员人工处理后确认：归档日志、记 confirm_navigation_recovery 操作日志、清标记。

    Args:
        request: 当前请求，只读 app.state 的数据库与状态目录装配。
        context: 全局认证的管理员上下文；成员为 403，且先于其他检查。

    Returns:
        HTTP 200，已清理的作业编号（文本，升序）；下一轮作业领取即放行排队的写作业。

    Raises:
        AuthenticationError: 未登录，401。
        AuthorizationError: Origin 不合法或不是管理员，403。
        PasswordChangeRequiredError: 必须改口令，403。
        ConflictError: 当前没有标记（已被别人确认），409。
        InputError: 标记损坏，400。
        ExternalError: 归档、删日志或数据库写入失败，502；标记保留。
        DefectError: 装配或时钟缺陷，500。

    Side Effects:
        写状态目录（归档变更记录、删写入日志）和数据库（操作日志与清标记）；不写导航层，不调用 recovery、atomic。
        操作日志的操作人是当前管理员，来源与请求编号取自服务端。

    Time Semantics:
        使用请求唯一 UTC 时刻；同步完成，不重试；崩在中途时标记保留、写操作继续被挡。
    """
    engine, paths = _dependencies(request)
    session_identity = identity(context)
    actor = ActorRef(session_identity.account.account_id, session_identity.account.display_name)
    result = acknowledge_recovery_block(
        engine, paths, AcknowledgeRequest(actor=actor, context=context.audit, now=context.now)
    )
    return AcknowledgeResponse(
        cleared_job_ids=tuple(str(job_id) for job_id in result.cleared_job_ids)
    )
