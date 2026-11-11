"""Lichtblick 同源托管（Web 入口层，M5-04/10），只读本地状态目录中的已安装网页。

认证沿用账号边界，路径隔离与文件传输复用 StaticFiles；不代理机器人或外网资源。
HTML 提取与 CSP 摘要使用标准库 HTMLParser、hashlib、base64，不执行包内脚本。
"""

import base64
import hashlib
from html.parser import HTMLParser
from http import HTTPStatus
from pathlib import Path
from typing import override

from fastapi import APIRouter, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from fastapi.staticfiles import StaticFiles

from rdp.api._asgi import ASGIApp, ASGIMessage, Receive, Send
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
# 评审实测：消息解码需要 eval，Plot 还会读取 blob/data；入口脚本只按安装内容的哈希放行。
# Emotion 样式需要内联；script-src 不使用 unsafe-inline，也不放行外网脚本和 HTTP 请求。
LICHTBLICK_CSP = (
    "default-src 'self'; connect-src 'self' ws: blob: data:; "
    "script-src 'self' 'wasm-unsafe-eval' 'unsafe-eval' {script_hashes}; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; "
    "worker-src 'self' blob:; media-src 'self' blob:; "
    "object-src 'none'; base-uri 'self'; frame-ancestors 'self'"
)


class _ViewerNotInstalledError(InputError):
    """本地网页未安装，给出可执行安装命令。"""

    http_status = HTTPStatus.NOT_FOUND


def with_lichtblick_cache_control(app: ASGIApp) -> ASGIApp:
    """为 Lichtblick 的所有 HTTP 响应启用浏览器缓存重验证。

    Args:
        app: 完整的下游 ASGI 应用，须包含错误响应边界；无单位。

    Returns:
        包装后的 ASGI 应用；仅 /lichtblick/ 下的响应统一带 Cache-Control: no-cache。
        其他路径、WebSocket 和 lifespan 原样传递，保留 ETag 等已有验证头。

    Raises:
        BaseException: 下游应用或收发回调抛出的异常原样传播，不在此转换错误。

    Side Effects:
        仅复制并修改 HTTP 响应起始消息的缓存头，不读写文件或保存请求状态。

    Time Semantics:
        无计时或等待；浏览器每次使用缓存前需向服务端验证资源是否变化。
    """

    async def wrapped(scope: ASGIMessage, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope.get("path", "").startswith("/lichtblick/"):
            await app(scope, receive, send)
            return

        async def send_with_cache_control(message: ASGIMessage) -> None:
            if message["type"] == "http.response.start":
                headers = [
                    (key, value)
                    for key, value in message.get("headers", [])
                    if key.lower() != b"cache-control"
                ]
                headers.append((b"cache-control", b"no-cache"))
                message = dict(message, headers=headers)
            await send(message)

        await app(scope, receive, send_with_cache_control)

    return wrapped


def configure_lichtblick(app: FastAPI, *, state_dir: Path) -> None:
    """绑定本地 Lichtblick 安装位置，并从已安装入口计算内嵌脚本的 CSP 哈希。

    Args:
        app: 当前 Web 应用，路由由 create_app 注册。
        state_dir: 配置解析后的状态根绝对路径，不由网页输入。

    Returns:
        无；后续静态请求使用此目录及应用独享的 CSP，未安装时不阻止平台启动。

    Raises:
        OSError: 已安装入口不可读。
        UnicodeError: 已安装入口不是有效 UTF-8 文本。

    Side Effects:
        只读已安装的 index.html 并缓存策略；不执行脚本、不创建或修改文件。

    Time Semantics:
        启动时同步计算一次；启动时未安装的，在安装后的首次请求计算，无轮询或重试。
        已安装版本的文件由部署方保持不变，与安装命令不覆盖已有版本的约定一致。
    """
    directory = lichtblick_directory(state_dir)
    app.state.lichtblick_dir = directory
    app.state.lichtblick_csp = _read_csp(directory)


class _InlineScriptParser(HTMLParser):
    """只收集无 src 的脚本文本，保留原始空白和实体，避免 CSP 哈希与浏览器不一致。"""

    def __init__(self) -> None:
        """复用标准 HTML 解析器，不用正则猜测脚本边界或 HTML 属性。"""
        super().__init__(convert_charrefs=False)
        self.hashes: list[str] = []
        self._inline = False
        self._parts: list[str] = []

    @override
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """外链脚本由 self 管理；只有没有 src 属性的脚本需要内容哈希。"""
        if tag == "script":
            self._inline = all(name != "src" for name, _ in attrs)
            self._parts = []

    @override
    def handle_data(self, data: str) -> None:
        """HTMLParser 对 script 使用原始文本模式，不解码脚本内的实体。"""
        if self._inline:
            self._parts.append(data)

    @override
    def handle_endtag(self, tag: str) -> None:
        """CSP 摘要只包含标签之间的 UTF-8 文本，不裁剪空白、不包含标签本身。"""
        if tag == "script" and self._inline:
            digest = hashlib.sha256("".join(self._parts).encode("utf-8")).digest()
            self.hashes.append(f"'sha256-{base64.b64encode(digest).decode('ascii')}'")
            self._inline = False


def _read_csp(directory: Path) -> str | None:
    """从安装入口生成策略；沿用 StaticFiles 的路径隔离，未安装时返回 None。"""
    path, metadata = StaticFiles(directory=directory, check_dir=False).lookup_path("index.html")
    if metadata is None:
        return None
    parser = _InlineScriptParser()
    # 文本读取的通用换行转换与 HTML 的 CRLF/CR 归一化一致；脚本其余空白保持原样。
    parser.feed(Path(path).read_text(encoding="utf-8"))
    parser.close()
    return LICHTBLICK_CSP.format(script_hashes=" ".join(parser.hashes))


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
        UnicodeError: 启动后首次安装的入口不是有效 UTF-8 文本。

    Side Effects:
        只读已安装网页；若启动时未安装，首次请求缓存入口脚本的 CSP 哈希。
        账号认证及续期沿用统一边界。

    Time Semantics:
        未安装时每次请求检查入口，已安装时共用缓存的策略；首次解析及文件读取均在线程池完成，
        无轮询或外部网络等待，不在每个资源请求上重新计算哈希。
    """
    directory = getattr(request.app.state, "lichtblick_dir", None)
    policy = getattr(request.app.state, "lichtblick_csp", None)
    if policy is None and isinstance(directory, Path):
        policy = await run_in_threadpool(_read_csp, directory)
        request.app.state.lichtblick_csp = policy
    if not isinstance(directory, Path) or policy is None:
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
    response.headers["content-security-policy"] = policy
    return response
