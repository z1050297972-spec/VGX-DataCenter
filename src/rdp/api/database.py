"""Web 入口层数据库装配与请求会话（工单 05），基础层不依赖 FastAPI。

核对本地 FastAPI 0.161.1 routing.request_response、dependencies.utils._solve_generator
和 concurrency.contextmanager_in_threadpool：scope=function 在发送响应前退出，
Exception 经 __exit__ 回到同步 yield；默认 request scope 则在发送响应后退出。
因此所有数据库依赖必须显式用 scope=function，流式生成器/后台任务不能继续用业务会话。
"""

from collections.abc import Generator
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from rdp.infra.db.connection import session_scope
from rdp.infra.db.migration import check_database_version
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    ExternalError,
)


def configure_database(app: FastAPI, engine: Engine) -> None:
    """校验数据库版本并为一个尚未启动的应用绑定调用方引擎。

    Args:
        app: create_app 创建的 FastAPI，尚未构建中间件栈，无单位。
        engine: create_database_engine 的本地文件引擎，无单位；必须由调用者拥有并保持可用。

    Returns:
        无；check_database_version 通过后把引擎绑定 app.state.database_engine；
        不提前打开业务会话，不迁移。重复调用属于装配错误，不替换已有引擎。

    Raises:
        InputError: 数据库缺失、无版本、落后、未知或领先，由版本闸门传播并提示先运行 migrate。
        ConflictError: 版本检查读取锁冲突。
        ExternalError: 文件权限或 I/O 故障。
        DefectError: app 已启动/已绑定、引擎不是本包本地 SQLite 引擎或迁移图错误。

    Side Effects:
        只读版本后修改 app 内存；失败不绑定引擎，不关闭调用者引擎、不配置日志。
        生产第 11 张入口必须创建并传引擎，停止接收请求、完成后台报告后 dispose；
        应用自身不 dispose，允许测试显式管理生命周期，不自动创建数据库。

    Time Semantics:
        在 create_app 返回前检查，单次数据库锁等待最多约 5 秒；不得与 migrate 并发。
    """
    if (
        app.middleware_stack is not None
        or hasattr(app.state, "database_engine")
        or not isinstance(cast(object, engine), Engine)
        or engine.dialect.name != "sqlite"
        or not engine.get_execution_options().get("rdp_managed")
        or not engine.url.database
    ):
        raise DefectError()
    check_database_version(Path(engine.url.database))
    app.state.database_engine = engine


def get_session(request: Request) -> Generator[Session, None, None]:
    """为一个请求提供可写工作单元，并在响应发送前提交或回滚。

    Args:
        request: 当前 FastAPI 请求；应用已 configure_database；依赖声明须使用
            Depends(get_session, scope="function")，默认 use_cache=True。

    Yields:
        一个 session_scope 的新写 Session；同请求重复依赖复用它，不与只读依赖混用，
        同一请求只能选择一种业务会话。进入 yield 前 BEGIN IMMEDIATE，关闭后不可继续使用。

    Raises:
        ExternalError: 未配置数据库（离线工厂模式），诊断说明“数据库未启用”，或数据库 I/O 失败。
        InputError: 数据库数据损坏。
        ConflictError: 写锁等待约 5 秒仍不可用，或数据库约束冲突。
        DefectError: 数据库编程错误。
        BaseException: 路由业务异常原样传播并回滚，不能吞掉；清理失败语义同 session_scope。

    Side Effects:
        成功提交；路由、序列化或提交失败回滚，关闭连接，不留下部分业务记录。
        FastAPI 在工作线程进入/退出同步依赖；只允许同步路由顺序操作该 Session，
        异步路由须把整个同步数据库操作移入线程，禁止在事件循环直接调用同步 SQL。
        报错持久化另开会话，不参与此回滚；流式正文或后台任务不得引用本 Session。

    Time Semantics:
        scope=function 使提交在 http.response.start 之前；路由 Exception 经 yield 的
        __exit__ 回传，可回滚并由统一边界报告。框架同步适配仅显式捕获 Exception，
        ASGI 取消不承诺立即打断正在运行的同步 SQL；连接必须最终关闭，不吞取消或伪造提交。
    """
    with session_scope(_request_engine(request, False)) as session:
        yield session


def get_read_session(request: Request) -> Generator[Session, None, None]:
    """为查询请求提供禁止升级为写事务的只读会话。

    Args:
        request: 已绑定数据库的当前请求；使用 Depends(get_read_session, scope="function")，
            默认缓存，同一请求不得同时使用 get_session。

    Yields:
        一个 session_scope(read_only=True) 的 Session，BEGIN 加 query_only，响应发送前结束；
        允许与其他进程的 WAL 写事务并发读取已提交内容。

    Raises:
        ExternalError: 无数据库模式，或权限/I/O 错误。
        InputError: 数据库或报错行损坏。
        ConflictError: SQLite 读取锁冲突。
        DefectError: 试图写入、其他 SQL/映射错误。
        BaseException: 路由异常原样传播；清理失败保留原异常，同 get_session。

    Side Effects:
        只读数据，正常结束读事务、异常回滚并关闭连接；不提交业务写入、不延长保留期。

    Time Semantics:
        scope=function，响应发送前释放快照；不等待将来的报错记录，不重试。
        线程、取消和流式限制与 get_session 相同。
    """
    with session_scope(_request_engine(request, True), read_only=True) as session:
        yield session


def _request_engine(request: Request, read_only: bool) -> Engine:
    """无数据库模式明确返回外部失败；拒绝同请求混用读写业务会话。"""
    engine = getattr(request.app.state, "database_engine", None)
    if engine is None:
        raise ExternalError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.EXTERNAL,
                    stage="数据库",
                    source="平台",
                    objects=(),
                    rule="业务接口必须配置数据库",
                    actual="数据库未启用",
                    expected="应用启动时显式绑定已迁移的数据库",
                    consequence="本次数据库请求未执行",
                    next_step="使用配置了数据库的生产入口启动应用",
                ),
            )
        )
    if not isinstance(engine, Engine):
        raise DefectError()
    previous = getattr(request.state, "rdp_business_mode", read_only)
    if previous != read_only:
        raise DefectError()
    request.state.rdp_business_mode = read_only
    return engine
