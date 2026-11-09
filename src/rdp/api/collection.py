"""采集登记 HTTP 入口：编排身份、事务及响应，不连接机器人或写导航层。

读写会话复用已有 function scope 依赖，响应发送前完成提交；领域写操作重验账号身份。
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.api._account_context import identity
from rdp.api._audit_views import actor
from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.api.collection_schemas import (
    MethodResponse,
    ModelOptionsResponse,
    PurposeResponse,
    RobotResponse,
    RobotsResponse,
    VocabularyResponse,
)
from rdp.api.database import get_read_session, get_session
from rdp.api.jobs import JobContext
from rdp.collection import service
from rdp.collection.models import RobotRow
from rdp.collection.types import MethodInput, PurposeInput, RobotInput
from rdp.infra.ids import MAX_SQLITE_INTEGER
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.robot_connection.keys import SshPublicKey, read_public_key

router = APIRouter(prefix="/api", tags=["机器人与采集词表"])
Context = Annotated[AccountRequestContext, Depends(get_authenticated_context)]
ReadSession = Annotated[Session, Depends(get_read_session, scope="function")]
WriteSession = Annotated[Session, Depends(get_session, scope="function")]
Identifier = Annotated[int, Path(ge=1, le=MAX_SQLITE_INTEGER)]


def _response[T: RobotResponse | MethodResponse | PurposeResponse](
    record: service.RegistryRecord, model: type[T]
) -> T:
    """复用历史账号响应适配，登记对象编号按本票契约保留整数。"""
    return model.model_validate(
        record.value.model_dump()
        | {
            "robot_id" if model is RobotResponse else "id": record.id,
            "status": record.status,
            "reference_count": record.reference_count,
            "created_by": actor(record.created_by, record.creator_deleted),
            "created_at": record.created_at,
            "updated_by": actor(record.updated_by, record.updater_deleted),
            "updated_at": record.updated_at,
        }
    )


@router.get("/robots/ssh-public-key", response_model=SshPublicKey)
def robot_ssh_public_key(
    robot_id: Annotated[int, Query(ge=1, le=MAX_SQLITE_INTEGER)],
    session: ReadSession,
    context: JobContext,
) -> SshPublicKey:
    """只读展示平台公钥和指定机器人的手动安装命令。

    Args:
        robot_id: 机器人永久编号，1 至 2^63-1；只从登记读取连接信息。
        session: 当前请求的只读数据库事务。
        context: 已登录成员或管理员，以及显式装配的状态目录。

    Returns:
        公钥一行与 ssh-copy-id 命令；worker 尚未生成时两项均为 None。

    Raises:
        CollectionNotFoundError: 指定机器人不存在，404。
        ExternalError: 状态服务未配置、公钥不可读或路径不安全，502。

    Side Effects:
        无；只读平台公钥与登记，既不读取私钥也不调用 SSH 或生成密钥。

    Time Semantics:
        不等待作业执行，公钥未生成立即返回；安装命令取当前登记快照。
    """
    return read_public_key(context.paths, session, robot_id)


@router.get("/robots", response_model=RobotsResponse)
def list_robots(session: ReadSession, context: Context) -> RobotsResponse:
    """列出全部机器人，包括停用项。

    Args:
        session: 请求只读业务事务。
        context: 已完成强制改密的成员或管理员。

    Returns:
        items 按 robot_id 升序，允许空列表。

    Raises:
        ExternalError: 查询数据库不可用，统一边界返回502。
        InputError: 历史字段损坏，统一边界返回400。

    Side Effects:
        无；仅查询机器人及历史账号存在性。

    Time Semantics:
        请求快照内完成列表，响应发送前结束读事务，无网络探测。
    """
    return RobotsResponse(
        items=tuple(
            _response(row, RobotResponse) for row in service.list_records(session, "robots")
        )
    )


@router.get("/robots/model-options", response_model=ModelOptionsResponse)
def robot_model_options(session: ReadSession, context: Context) -> ModelOptionsResponse:
    """合并机器人登记与数据集索引中的型号候选。

    Args:
        session: 同一请求只读会话。
        context: 已登录且完成改密的成员或管理员。

    Returns:
        items 去重、排序，不包含空值；允许输入候选以外的新型号。

    Raises:
        ExternalError: 数据集或机器人索引查询不可用，502。

    Side Effects:
        无；只读取数据库，不扫描导航层或存储根。

    Time Semantics:
        两组候选来自同一数据库快照，不等待新扫描。
    """
    values = set(session.scalars(select(RobotRow.robot_model)))
    values.update(value for value in session.scalars(select(DatasetRow.robot_model)) if value)
    return ModelOptionsResponse(items=tuple(sorted(values)))


@router.get("/collection-vocabulary", response_model=VocabularyResponse)
def collection_vocabulary(session: ReadSession, context: Context) -> VocabularyResponse:
    """返回采集方式和用途两个完整词表。

    Args:
        session: 请求只读事务，不升级为写会话。
        context: 已认证成员或管理员，强制改密已完成。

    Returns:
        methods 和 purposes 分别按 id 升序，包含停用项及历史身份。

    Raises:
        ExternalError: 词表读取失败，502。
        InputError: 词表历史数据损坏，400。

    Side Effects:
        无；读取两个词表及账号存在性，不补写初始值。

    Time Semantics:
        两个词表共用一个请求快照，结束读事务后发送响应。
    """
    return VocabularyResponse(
        methods=tuple(
            _response(row, MethodResponse) for row in service.list_records(session, "methods")
        ),
        purposes=tuple(
            _response(row, PurposeResponse) for row in service.list_records(session, "purposes")
        ),
    )


@router.post("/robots", response_model=RobotResponse, status_code=201)
def create_robot(body: RobotInput, session: WriteSession, context: Context) -> RobotResponse:
    """创建机器人并记录操作日志。

    Args:
        body: 机器人完整可编辑字段，按工单校验并规范化。
        session: 创建机器人使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        201，创建后的机器人及历史身份快照。

    Raises:
        ConflictError: 机器人唯一字段已占用，409。
        RequestValidationError: 机器人输入字段不合法，422。
        AuthenticationError: 创建前会话或账号失效，401。
        ExternalError: 创建机器人的数据库写入失败，502。

    Side Effects:
        创建机器人与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再创建，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送201，不执行外部机器人通信。
    """
    record = service.save_record(
        session,
        "robots",
        body,
        identifier=None,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, RobotResponse)


@router.put("/robots/{robot_id}", response_model=RobotResponse)
def update_robot(
    robot_id: Identifier, body: RobotInput, session: WriteSession, context: Context
) -> RobotResponse:
    """修改机器人并记录操作日志。

    Args:
        robot_id: 机器人永久编号，1至2^63-1。
        body: 机器人完整可编辑字段，按工单校验并规范化。
        session: 修改机器人使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，修改后的机器人及历史身份快照。

    Raises:
        CollectionNotFoundError: 机器人编号不存在，404。
        ConflictError: 机器人唯一字段已占用，409。
        RequestValidationError: 机器人输入字段不合法，422。
        AuthenticationError: 修改前会话或账号失效，401。
        ExternalError: 修改机器人的数据库写入失败，502。

    Side Effects:
        修改机器人与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再修改，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.save_record(
        session,
        "robots",
        body,
        identifier=robot_id,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, RobotResponse)


@router.post("/robots/{robot_id}/retire", response_model=RobotResponse)
def retire_robot(robot_id: Identifier, session: WriteSession, context: Context) -> RobotResponse:
    """停用机器人并记录操作日志。

    Args:
        robot_id: 机器人永久编号，1至2^63-1。
        session: 停用机器人使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，停用后的机器人及历史身份快照。

    Raises:
        CollectionNotFoundError: 机器人编号不存在，404。
        AuthenticationError: 停用前会话或账号失效，401。
        ExternalError: 停用机器人的数据库写入失败，502。

    Side Effects:
        停用机器人与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再停用，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.set_status(
        session,
        "robots",
        robot_id,
        "retired",
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, RobotResponse)


@router.post("/robots/{robot_id}/restore", response_model=RobotResponse)
def restore_robot(robot_id: Identifier, session: WriteSession, context: Context) -> RobotResponse:
    """恢复机器人并记录操作日志。

    Args:
        robot_id: 机器人永久编号，1至2^63-1。
        session: 恢复机器人使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，恢复后的机器人及历史身份快照。

    Raises:
        CollectionNotFoundError: 机器人编号不存在，404。
        AuthenticationError: 恢复前会话或账号失效，401。
        ExternalError: 恢复机器人的数据库写入失败，502。

    Side Effects:
        恢复机器人与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再恢复，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.set_status(
        session,
        "robots",
        robot_id,
        "active",
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, RobotResponse)


@router.delete("/robots/{robot_id}", response_class=Response, status_code=204)
def delete_robot(robot_id: Identifier, session: WriteSession, context: Context) -> Response:
    """删除机器人并记录操作日志。

    Args:
        robot_id: 机器人永久编号，1至2^63-1。
        session: 删除机器人使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        204，无响应体。

    Raises:
        CollectionNotFoundError: 机器人编号不存在，404。
        ConflictError: 机器人仍有数据集引用，409，提示改用停用。
        AuthenticationError: 删除前会话或账号失效，401。
        ExternalError: 删除机器人的数据库写入失败，502。

    Side Effects:
        删除机器人与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再删除，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送204，不执行外部机器人通信。
    """
    service.delete_record(
        session,
        "robots",
        robot_id,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return Response(status_code=204)


@router.post("/collection-vocabulary/methods", response_model=MethodResponse, status_code=201)
def create_collection_method(
    body: MethodInput, session: WriteSession, context: Context
) -> MethodResponse:
    """创建采集方式并记录操作日志。

    Args:
        body: 采集方式完整可编辑字段，按工单校验并规范化。
        session: 创建采集方式使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        201，创建后的采集方式及历史身份快照。

    Raises:
        ConflictError: 采集方式唯一字段已占用，409。
        RequestValidationError: 采集方式输入字段不合法，422。
        AuthenticationError: 创建前会话或账号失效，401。
        ExternalError: 创建采集方式的数据库写入失败，502。

    Side Effects:
        创建采集方式与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再创建，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送201，不执行外部机器人通信。
    """
    record = service.save_record(
        session,
        "methods",
        body,
        identifier=None,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, MethodResponse)


@router.put("/collection-vocabulary/methods/{id}", response_model=MethodResponse)
def update_collection_method(
    id: Identifier, body: MethodInput, session: WriteSession, context: Context
) -> MethodResponse:
    """修改采集方式并记录操作日志。

    Args:
        id: 采集方式永久编号，1至2^63-1。
        body: 采集方式完整可编辑字段，按工单校验并规范化。
        session: 修改采集方式使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，修改后的采集方式及历史身份快照。

    Raises:
        CollectionNotFoundError: 采集方式编号不存在，404。
        ConflictError: 采集方式唯一字段已占用，409。
        RequestValidationError: 采集方式输入字段不合法，422。
        AuthenticationError: 修改前会话或账号失效，401。
        ExternalError: 修改采集方式的数据库写入失败，502。

    Side Effects:
        修改采集方式与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再修改，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.save_record(
        session,
        "methods",
        body,
        identifier=id,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, MethodResponse)


@router.post("/collection-vocabulary/methods/{id}/retire", response_model=MethodResponse)
def retire_collection_method(
    id: Identifier, session: WriteSession, context: Context
) -> MethodResponse:
    """停用采集方式并记录操作日志。

    Args:
        id: 采集方式永久编号，1至2^63-1。
        session: 停用采集方式使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，停用后的采集方式及历史身份快照。

    Raises:
        CollectionNotFoundError: 采集方式编号不存在，404。
        AuthenticationError: 停用前会话或账号失效，401。
        ExternalError: 停用采集方式的数据库写入失败，502。

    Side Effects:
        停用采集方式与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再停用，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.set_status(
        session,
        "methods",
        id,
        "retired",
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, MethodResponse)


@router.post("/collection-vocabulary/methods/{id}/restore", response_model=MethodResponse)
def restore_collection_method(
    id: Identifier, session: WriteSession, context: Context
) -> MethodResponse:
    """恢复采集方式并记录操作日志。

    Args:
        id: 采集方式永久编号，1至2^63-1。
        session: 恢复采集方式使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，恢复后的采集方式及历史身份快照。

    Raises:
        CollectionNotFoundError: 采集方式编号不存在，404。
        AuthenticationError: 恢复前会话或账号失效，401。
        ExternalError: 恢复采集方式的数据库写入失败，502。

    Side Effects:
        恢复采集方式与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再恢复，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.set_status(
        session,
        "methods",
        id,
        "active",
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, MethodResponse)


@router.delete("/collection-vocabulary/methods/{id}", response_class=Response, status_code=204)
def delete_collection_method(id: Identifier, session: WriteSession, context: Context) -> Response:
    """删除采集方式并记录操作日志。

    Args:
        id: 采集方式永久编号，1至2^63-1。
        session: 删除采集方式使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        204，无响应体。

    Raises:
        CollectionNotFoundError: 采集方式编号不存在，404。
        ConflictError: 采集方式仍有数据集引用，409，提示改用停用。
        AuthenticationError: 删除前会话或账号失效，401。
        ExternalError: 删除采集方式的数据库写入失败，502。

    Side Effects:
        删除采集方式与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再删除，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送204，不执行外部机器人通信。
    """
    service.delete_record(
        session,
        "methods",
        id,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return Response(status_code=204)


@router.post("/collection-vocabulary/purposes", response_model=PurposeResponse, status_code=201)
def create_collection_purpose(
    body: PurposeInput, session: WriteSession, context: Context
) -> PurposeResponse:
    """创建用途并记录操作日志。

    Args:
        body: 用途完整可编辑字段，按工单校验并规范化。
        session: 创建用途使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        201，创建后的用途及历史身份快照。

    Raises:
        ConflictError: 用途唯一字段已占用，409。
        RequestValidationError: 用途输入字段不合法，422。
        AuthenticationError: 创建前会话或账号失效，401。
        ExternalError: 创建用途的数据库写入失败，502。

    Side Effects:
        创建用途与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再创建，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送201，不执行外部机器人通信。
    """
    record = service.save_record(
        session,
        "purposes",
        body,
        identifier=None,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, PurposeResponse)


@router.put("/collection-vocabulary/purposes/{id}", response_model=PurposeResponse)
def update_collection_purpose(
    id: Identifier, body: PurposeInput, session: WriteSession, context: Context
) -> PurposeResponse:
    """修改用途并记录操作日志。

    Args:
        id: 用途永久编号，1至2^63-1。
        body: 用途完整可编辑字段，按工单校验并规范化。
        session: 修改用途使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，修改后的用途及历史身份快照。

    Raises:
        CollectionNotFoundError: 用途编号不存在，404。
        ConflictError: 用途唯一字段已占用，409。
        RequestValidationError: 用途输入字段不合法，422。
        AuthenticationError: 修改前会话或账号失效，401。
        ExternalError: 修改用途的数据库写入失败，502。

    Side Effects:
        修改用途与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再修改，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.save_record(
        session,
        "purposes",
        body,
        identifier=id,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, PurposeResponse)


@router.post("/collection-vocabulary/purposes/{id}/retire", response_model=PurposeResponse)
def retire_collection_purpose(
    id: Identifier, session: WriteSession, context: Context
) -> PurposeResponse:
    """停用用途并记录操作日志。

    Args:
        id: 用途永久编号，1至2^63-1。
        session: 停用用途使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，停用后的用途及历史身份快照。

    Raises:
        CollectionNotFoundError: 用途编号不存在，404。
        AuthenticationError: 停用前会话或账号失效，401。
        ExternalError: 停用用途的数据库写入失败，502。

    Side Effects:
        停用用途与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再停用，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.set_status(
        session,
        "purposes",
        id,
        "retired",
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, PurposeResponse)


@router.post("/collection-vocabulary/purposes/{id}/restore", response_model=PurposeResponse)
def restore_collection_purpose(
    id: Identifier, session: WriteSession, context: Context
) -> PurposeResponse:
    """恢复用途并记录操作日志。

    Args:
        id: 用途永久编号，1至2^63-1。
        session: 恢复用途使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        200，恢复后的用途及历史身份快照。

    Raises:
        CollectionNotFoundError: 用途编号不存在，404。
        AuthenticationError: 恢复前会话或账号失效，401。
        ExternalError: 恢复用途的数据库写入失败，502。

    Side Effects:
        恢复用途与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再恢复，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送200，不执行外部机器人通信。
    """
    record = service.set_status(
        session,
        "purposes",
        id,
        "active",
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return _response(record, PurposeResponse)


@router.delete("/collection-vocabulary/purposes/{id}", response_class=Response, status_code=204)
def delete_collection_purpose(id: Identifier, session: WriteSession, context: Context) -> Response:
    """删除用途并记录操作日志。

    Args:
        id: 用途永久编号，1至2^63-1。
        session: 删除用途使用的已持锁写事务，发送响应前提交。
        context: 允许成员和管理员，携带请求身份、UTC时刻和审计来源。

    Returns:
        204，无响应体。

    Raises:
        CollectionNotFoundError: 用途编号不存在，404。
        ConflictError: 用途仍有数据集引用，409，提示改用停用。
        AuthenticationError: 删除前会话或账号失效，401。
        ExternalError: 删除用途的数据库写入失败，502。

    Side Effects:
        删除用途与对应操作日志同事务提交；发生异常则全部回滚。

    Time Semantics:
        领域层先重验身份再删除，采用本请求UTC时刻；修改时刻不倒退。
        提交完成后才发送204，不执行外部机器人通信。
    """
    service.delete_record(
        session,
        "purposes",
        id,
        context=service.ChangeContext(identity(context), context.now, context.audit),
    )
    return Response(status_code=204)
