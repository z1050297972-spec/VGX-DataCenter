"""Lichtblick 同源托管（Web 入口层，M5-04），只读本地状态目录中的已安装网页。

认证沿用账号边界，路径隔离与文件传输复用 StaticFiles；不代理机器人或外网资源。
"""

from http import HTTPStatus
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from rdp.api.robot_profiles import AuthenticatedContext
from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)
from rdp.infra.lichtblick import LICHTBLICK_VERSION, lichtblick_directory

router = APIRouter()

# M5-04/A6：本地字体和图像可用，扩展市场、地图瓦片、外链脚本全部禁止。
# Lichtblick 使用 blob worker 与 WASM，Emotion 样式需要内联；不放行远端脚本或 eval。
LICHTBLICK_CSP = (
    "default-src 'self'; connect-src 'self' ws:; "
    "script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; "
    "worker-src 'self' blob:; media-src 'self' blob:; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
)


class _ViewerNotInstalledError(InputError):
    """本地网页未安装，给出可执行安装命令。"""

    http_status = HTTPStatus.NOT_FOUND


def configure_lichtblick(app: FastAPI, *, state_dir: Path) -> None:
    """为应用绑定本地 Lichtblick 安装位置，允许稍后离线安装。

    Args:
        app: 当前 Web 应用，路由由 create_app 注册。
        state_dir: 配置解析后的状态根绝对路径，不由网页输入。

    Returns:
        无；后续静态请求读取此目录。

    Raises:
        无。

    Side Effects:
        只设置应用实例上的路径，不创建目录或打开文件。

    Time Semantics:
        启动时装配一次；安装完成后的下一次请求即可读取，不必重启。
    """
    app.state.lichtblick_dir = lichtblick_directory(state_dir)


@router.get("/lichtblick/{path:path}", include_in_schema=False)
async def serve_lichtblick(path: str, request: Request, account: AuthenticatedContext) -> Response:
    """向登录账号提供锁定版本的查看器静态文件并限制外部连接。

    Args:
        path: 相对 /lichtblick/ 的资源路径，空串读取 index.html；不允许越出安装目录。
        request: 当前请求，用于取得应用安装目录和 StaticFiles scope。
        account: 已完成改密的登录身份，不向查看器输出账号凭据。

    Returns:
        静态响应，WASM 为 application/wasm，带限制外网的 CSP，不设置 X-Frame-Options。

    Raises:
        _ViewerNotInstalledError: 未装配目录或缺少入口文件，404 诊断附安装命令。
        HTTPException: StaticFiles 找不到资源或路径越界，404；不会回退平台首页。
        OSError: 本地静态资源读取失败，由统一错误边界报告。

    Side Effects:
        无（只读已安装网页）；账号认证及续期沿用统一边界。

    Time Semantics:
        每次请求检查安装入口；文件读取由 StaticFiles 在线程池完成，无轮询或外部网络等待。
    """
    directory = getattr(request.app.state, "lichtblick_dir", None)
    if not isinstance(directory, Path) or not (directory / "index.html").is_file():
        raise _ViewerNotInstalledError(
            (
                Diagnostic(
                    level=DiagnosticLevel.ERROR,
                    category=DiagnosticCategory.INPUT,
                    stage="打开实时预览",
                    source="平台",
                    objects=(DiagnosticObject(key="version", value=LICHTBLICK_VERSION),),
                    rule="lichtblick.not_installed",
                    actual="Lichtblick 网页包尚未安装",
                    expected=f"状态目录中存在已校验的 Lichtblick {LICHTBLICK_VERSION} 网页包",
                    consequence="无法嵌入实时预览查看器",
                    next_step="运行 rdp install-lichtblick /本地路径/lichtblick-web.tar.gz",
                ),
            )
        )
    response = await StaticFiles(directory=directory).get_response(
        path or "index.html", request.scope
    )
    if path.endswith(".wasm"):
        response.headers["content-type"] = "application/wasm"
    response.headers["content-security-policy"] = LICHTBLICK_CSP
    return response
