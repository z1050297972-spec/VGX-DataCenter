"""Web 入口层，提供应用工厂及 SPA 托管边界，不访问导航层或存储根。

静态托管使用 FastAPI 再导出的 StaticFiles；不自行实现文件传输或直接依赖 starlette。
依据：ADR 0001、0002、0005，M0 工单 02；接口与静态托管共享一个应用入口。
"""

import stat
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from rdp.api.health import HealthResponse, get_health


def _unknown_api() -> Response:
    """保留 API 命名空间，避免同名静态文件或 SPA 回退冒充 JSON 接口。"""
    return JSONResponse({"detail": "Not Found"}, status_code=404)


def create_app(web_dist: Path | None) -> FastAPI:
    """创建健康接口及可选的前端静态托管应用，不启动服务器。

    Args:
        web_dist: 前端构建目录路径，无单位；相对路径按调用时工作目录解析。
            None 表示只提供 JSON 接口；否则必须是存在的目录，包含普通文件 index.html。
            调用方应传本地可信构建产物目录，不传数据目录。

    Returns:
        独立的 FastAPI 应用；GET /api/health 返回 200 和 {"status": "ok"}，
        响应模型为 HealthResponse，并出现在 OpenAPI 中。
        web_dist 为 None 时 / 返回 404；给定目录时存在的静态文件原样返回，
        /api/ 以外找不到文件的 GET 返回 index.html，供前端处理路由。
        /api 及 /api/ 下未知路径返回 404 JSON，绝不返回 index.html；
        非 GET 请求不使用 SPA 回退。静态服务不允许读取目录外文件或跟随越界软链接。

    Raises:
        FileNotFoundError: 创建时 web_dist 不存在，或其中 index.html 不存在。
        NotADirectoryError: 创建时 web_dist 存在但不是目录。
        ValueError: 创建时 index.html 存在但不是普通文件，或解析后越出构建目录。
        OSError: 创建时读取构建目录或入口文件状态失败，例如权限不足。

    Side Effects:
        无（只读构建目录及入口文件状态，注册内存中的路由；不建 socket、不写磁盘）。
        接收请求后只读构建产物；不访问导航层、存储根或数据库。

    Time Semantics:
        同步创建，返回前完成目录校验；无重试、轮询或时区转换。
        构建产物由部署方保持稳定，创建时校验不保证后续请求时文件仍存在。
    """
    app = FastAPI(title="机器人数据管理平台", version="0.1.0")
    app.add_api_route("/api/health", get_health, methods=["GET"], response_model=HealthResponse)
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
    return app
