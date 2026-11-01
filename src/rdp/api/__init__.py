"""Web 入口层，提供应用工厂及 SPA 托管边界，工厂本身不访问导航层或存储根。

静态托管使用 FastAPI 再导出的 StaticFiles；不自行实现文件传输或直接依赖 starlette。
依据：ADR 0001、0002、0005，M0 工单 02/03；接口与静态托管共享一个应用入口。
"""

import logging
import stat
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import override
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from rdp.api._asgi import ASGIApp as _ASGIApp
from rdp.api._asgi import ASGIMessage as _ASGIMessage
from rdp.api._asgi import Receive as _Receive
from rdp.api._asgi import Send as _Send
from rdp.api.account_auth import install_account_security
from rdp.api.accounts import router as accounts_router
from rdp.api.audit import router as audit_router
from rdp.api.data_origin import router as data_origin_router
from rdp.api.database import configure_database
from rdp.api.datasets import router as datasets_router
from rdp.api.datasets.creation import router as dataset_creation_router
from rdp.api.datasets.fields import router as field_edit_router
from rdp.api.download_tokens import router as download_tokens_router
from rdp.api.error_details import get_error_details
from rdp.api.errors import ErrorBoundary, install_error_handlers
from rdp.api.file_viewer import router as file_viewer_router
from rdp.api.health import HealthResponse, get_health
from rdp.api.jobs import router as jobs_router
from rdp.api.jobs import worker_router
from rdp.api.navigation import router as navigation_router
from rdp.api.navigation_writes import router as navigation_writes_router
from rdp.api.storage import router as storage_router
from rdp.api.version import configure_version
from rdp.infra.db.records import ErrorRecord
from rdp.infra.logging import log_context

logger = logging.getLogger(__name__)


class RequestIdMiddleware:
    """入口层的 ASGI 请求关联边界，包在框架错误处理中间件之外，不记录访问日志。"""

    def __init__(self, app: _ASGIApp) -> None:
        """保存下游 ASGI 应用，不启动或调用它。

        Args:
            app: 下游 ASGI 应用，无单位；必须可异步调用，生产中为完整的 FastAPI 中间件栈。

        Returns:
            无。得到独立中间件实例，不在实例上保存请求级可变状态。

        Raises:
            无。

        Side Effects:
            无。

        Time Semantics:
            构造时不生成编号、不读取时钟。
        """
        self._app = app

    async def __call__(self, scope: _ASGIMessage, receive: _Receive, send: _Send) -> None:
        """为 HTTP 请求绑定服务端编号，并把同一编号写入响应头。

        Args:
            scope: ASGI scope 开放字典，无单位；HTTP、WebSocket 或 lifespan 类型。
            receive: 无参数的异步 ASGI 接收回调，遵循服务器消息协议。
            send: 异步 ASGI 发送回调，接收一条响应消息，遵循服务器消息协议。

        Returns:
            无。HTTP 每次新建 uuid.uuid4().hex（32 位小写十六进制，v4/variant 位有效）；
            无条件忽略客户端 X-Request-ID，防止伪造关联号。每个 http.response.start
            用该编号替换所有已有同名响应头，仅保留一个 X-Request-ID；
            包括 2xx、3xx、4xx 和框架产生的 500。WebSocket/lifespan 原样透传，不生成编号。

        Raises:
            BaseException: 下游应用、receive 或 send 抛出的异常（含取消）原样传播；
                仍恢复上下文，不在此处转成诊断或重复打错误日志。

        Side Effects:
            HTTP 调用期间通过 rdp.infra.logging.log_context 绑定 request_id；
            退出后恢复原值，并发请求互不串号，job_id 保留原绑定。
            只复制并修改发送的响应起始消息及其 headers，不修改 scope 或下游消息对象。
            不记录任何访问日志；业务代码在请求内自行记录的日志自动带同一编号。
            下游尚未发送响应就失败时，本中间件不制造响应；若框架产生 500 则照常加头。

        Time Semantics:
            绑定覆盖整个下游 ASGI 调用，直到流式响应和后台任务完成或取消；
            不测量耗时、不阻塞事件循环、不读取墙钟，编号不含时间语义。
        """
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        request_id = uuid4().hex

        async def send_with_id(message: _ASGIMessage) -> None:
            """复制起始消息，避免修改下游复用的 header 列表。"""
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"x-request-id"
                ]
                headers.append((b"x-request-id", request_id.encode("ascii")))
                message = dict(message, headers=headers)
            await send(message)

        with log_context(request_id=request_id):
            await self._app(scope, receive, send_with_id)


class _RequestContextApp(FastAPI):
    """仅把请求上下文包到完整框架栈外，覆盖框架生成的 500 及流式响应。"""

    @override
    def build_middleware_stack(self) -> _ASGIApp:
        """返回 RequestIdMiddleware 包装的父类中间件栈；构建时不绑定编号或改变路由。"""
        # 依赖 Starlette 的 build_middleware_stack 包含错误处理中间件这一行为。
        # 升级 FastAPI/Starlette 时重看此方法，并重跑框架 500 的响应头契约测试。
        return RequestIdMiddleware(ErrorBoundary(super().build_middleware_stack()))


def _unknown_api() -> Response:
    """保留 API 命名空间，避免同名静态文件或 SPA 回退冒充 JSON 接口。"""
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def create_app(
    web_dist: Path | None,
    *,
    database: Engine | None,
    clock: Callable[[], datetime] | None = None,
    platform_version: str | None = None,
) -> FastAPI:
    """创建健康接口及可选的前端静态托管应用，不启动服务器。

    Args:
        web_dist: 前端构建目录路径，无单位；相对路径按调用时工作目录解析。
            None 表示只提供 JSON 接口；否则必须是存在的目录，包含普通文件 index.html。
            调用方应传本地可信构建产物目录，不传数据目录。
        database: 可选的 create_database_engine 引擎，无单位；必须显式传入；None 仅供离线 OpenAPI
            与无数据库测试。生产第 11 张入口必须显式传入，不允许用无数据库模式服务业务。
            调用者拥有生命周期，应用停止并完成报告后由调用者 dispose，工厂不接管。
        clock: 请求时钟，无单位；None 为 UTC 墙钟，测试可注入固定 aware datetime 回调；
            账号请求只取一次，不接受客户端时刻；非法返回值或回调失败由入口归 DefectError。
        platform_version: 生产入口传入的版本快照，1-128 个码点，无控制字符；
            None 仅用于离线导出/独立测试，版本接口返回“未知 (未知)”，不在工厂发现部署。

    Returns:
        独立的 FastAPI 应用；GET /api/health 返回 200 和 {"status": "ok"}，
        响应模型为 HealthResponse，并出现在 OpenAPI 中。
        web_dist 为 None 时 / 返回 404；给定目录时存在的静态文件原样返回，
        /api/ 以外找不到文件的 GET 返回 index.html，供前端处理路由。
        /api 及 /api/ 下未知路径返回 404 JSON，绝不返回 index.html；
        非 GET 请求不使用 SPA 回退。静态服务不允许读取目录外文件或跟随越界软链接。
        应用包含 RequestIdMiddleware，包在框架错误处理中间件之外；每次 HTTP 请求
        生成 uuid4().hex 请求编号，忽略客户端同名头，所有已发送响应含唯一 X-Request-ID。
        统一处理四类异常和参数校验失败，返回 application/problem+json；未知异常只报告一次。
        错误编号等于请求编号，程序缺陷响应不含 traceback；框架 HTTP 错误保留原格式。
        FastAPI 自带的 /docs、/redoc、/openapi.json 无条件关闭，与 database 是否提供无关。
        app.openapi() 仍按需生成诊断 schema 和路由定义，openapi_export 继续离线导出。
        登记 GET /api/errors/{error_id} 及 ErrorRecord 响应模型；database
        非空时返回前通过 configure_database 检查版本。None 模式仍登记详情 schema，
        查询返回带诊断的 ExternalError 502，缺陷只写日志、不落表。

        账号路由进入 OpenAPI；统一安装 account_auth 的默认拒绝边界，
        仅 GET 健康和 POST 登录免身份检查；详情接口所有已登录且已完成改密的账号可看。
        请求判定按 Origin→公开操作→认证→强制改密→角色→路由匹配→参数校验；S1 兜底最后区分 404/405。
        健康/登录公开路径的错误方法不要求身份，但非安全方法必须先有正确 Origin 才返回 405/Allow。
        第 7 张另登记 /api/audit/operations、/logins 和 /retention 的管理员路由；
        应用工厂只登记日志 schema 和权限分类，不负责激活 0003 或日志模型。
        第 8 张登记 /api/jobs 与 /api/worker/status，全部使用 get_authenticated_context；
        显式状态目录和作业登记表由 Web 启动入口调用 configure_jobs 注入，不发现默认 home。
        第 10 张登记 GET /api/storage-roots，所有登录账号可看；configure_storage 单独装配挂载检查。
        第 11 张通过 configure_version 登记 GET /api/version，版本 schema 同样出现在离线 OpenAPI；
        路径先于 API 兜底和静态挂载，沿用已登录且完成改密的认证边界，不改变健康响应。
        M1 第03张登记 /api/datasets 路由及展示类型；服务由 configure_datasets 显式装配，
        离线导出不读取导航，详情请求的导航只读边界由数据集服务负责。

    Raises:
        FileNotFoundError: 创建时 web_dist 不存在，或其中 index.html 不存在。
        NotADirectoryError: 创建时 web_dist 存在但不是目录。
        ValueError: 创建时 index.html 存在但不是普通文件，或解析后越出构建目录。
        OSError: 创建时读取构建目录或入口文件状态失败，例如权限不足。
        InputError: 数据库缺失/无版本/落后/领先/未知，拒绝创建并提示先运行 migrate。
        ConflictError: 数据库版本检查锁冲突。
        ExternalError: 数据库权限或 I/O 失败。
        DefectError: 引擎或迁移图配置错误，或 platform_version 非空但不符合版本文字约束。

    Side Effects:
        只读构建目录及入口文件状态，注册内存路由；有数据库时初始化默认 Argon2 编码器及假哈希，
        其资源和失败语义见 install_account_security；不建 socket、不写磁盘。
        静态托管请求只读构建产物；数据集详情只读导航；M1.5查看器独立带超时只读存储根。
        database 非空时只读校验版本，失败不迁移、不 dispose 调用者引擎；
        请求业务会话和缺陷报错会话彼此独立，报错失败不掩盖原 500，详见
        errors.report_error_with_database。
        请求处理期间绑定 request_id contextvar，业务日志自动关联响应编号，退出时恢复；
        中间件本身不产生访问日志，包含 /api/health；不在应用工厂配置全局 logger。

    Time Semantics:
        同步创建，返回前完成目录校验；无重试、轮询或时区转换。
        database 非空时版本检查可等待 SQLite 锁约 5 秒；业务和报错会话的时间预算见各自契约。
        构建产物由部署方保持稳定，创建时校验不保证后续请求时文件仍存在。
        请求绑定持续到下游 ASGI 调用结束（含流式响应、后台任务），异常或取消也恢复。
    """
    app = _RequestContextApp(
        title="机器人数据管理平台", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.accounts_clock = clock
    if database is not None:
        configure_database(app, database)
    app.add_api_route("/api/health", get_health, methods=["GET"], response_model=HealthResponse)
    app.add_api_route(
        "/api/errors/{error_id}",
        get_error_details,
        methods=["GET"],
        response_model=ErrorRecord,
        # 详情允许所有登录账号访问；运行时由统一边界保护，文档显式声明 cookie。
        openapi_extra={"security": [{"SessionCookie": []}]},
    )
    # 账号路由与既有 API 共用鉴权、时钟和 S1 兜底。
    app.include_router(accounts_router)
    # 07 日志接口登记管理员路径和 OpenAPI；全局边界在参数校验前识别 get_admin_context。
    app.include_router(audit_router)
    # 08 作业和心跳均允许全部登录账号，复用全局鉴权和同源写请求边界。
    app.include_router(jobs_router)
    app.include_router(download_tokens_router)
    # 数据集路由与M0共享认证/Origin及统一诊断；必须先于API兜底登记，离线可导出类型。
    app.include_router(datasets_router)
    app.include_router(dataset_creation_router)
    app.include_router(navigation_writes_router)
    app.include_router(file_viewer_router)
    app.include_router(storage_router)
    app.include_router(worker_router)
    # M1-07：导航层恢复失败标记；读全员、确认仅管理员，只碰数据库和状态目录。
    app.include_router(navigation_router)
    app.include_router(data_origin_router)
    app.include_router(field_edit_router)
    configure_version(
        app, version=platform_version if platform_version is not None else "未知 (未知)"
    )
    # 已知接口优先；兜底必须在静态挂载之前，不能让构建目录里的 api/ 文件遮蔽接口。
    for path in ("/api", "/api/{unknown:path}"):
        app.add_api_route(
            path,
            _unknown_api,
            include_in_schema=False,
            methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE"],
        )
    if web_dist is not None:
        # 固定创建时的绝对目录，后续 cwd 改动不能切换应用所服务的文件。
        web_dist = web_dist.resolve()
        # 主动 stat 保留不存在、无权限等原始 OSError，不用 is_dir 吞掉错误原因。
        if not stat.S_ISDIR(web_dist.stat().st_mode):
            raise NotADirectoryError(f"构建路径不是目录: {web_dist}")
        index = web_dist / "index.html"
        if not stat.S_ISREG(index.stat().st_mode):
            raise ValueError(f"入口不是普通文件: {index}")
        # 提前拒绝入口软链接越界；普通资源的路径约束由 StaticFiles 继续负责。
        if not index.resolve().is_relative_to(web_dist):
            raise ValueError(f"入口越出构建目录: {index}")
        # 沿用 StaticFiles 默认的 html=False；首页与 SPA 路由回退统一由下方处理。
        static_files = StaticFiles(directory=web_dist)

        async def _spa_fallback(request: Request, _error: Exception) -> Response:
            """把不存在的前端路由交给首页，文件传输仍由 StaticFiles 负责。"""
            # 仅前端 GET 导航允许回退；API 业务异常与其他方法保留通用 404 JSON。
            path = request.url.path
            if request.method != "GET" or path == "/api" or path.startswith("/api/"):
                return JSONResponse(
                    {"detail": getattr(_error, "detail", "Not Found")},
                    status_code=404,
                    headers=getattr(_error, "headers", None),
                )
            return await static_files.get_response("index.html", request.scope)

        app.add_exception_handler(404, _spa_fallback)
        app.mount("/", static_files)
    install_error_handlers(app)
    install_account_security(app)
    return app
