"""Web 入口层，提供应用工厂及 SPA 托管边界，不访问导航层或存储根。

静态托管使用 FastAPI 再导出的 StaticFiles；不自行实现文件传输或直接依赖 starlette。
依据：ADR 0001、0002、0005，M0 工单 02；A2 只交契约，B 实现路由及托管。
"""

from pathlib import Path

from fastapi import FastAPI


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
    raise NotImplementedError
