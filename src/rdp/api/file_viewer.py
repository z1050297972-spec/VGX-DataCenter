"""原文件只读HTTP边界（M1.5-01），沿用全局登录与五段诊断。

不使用FileResponse自行按路径打开：查看器需逐分量防换链、O_NOATIME和每块存储超时。
单段Range按HTTP字节位置计算，原字节传输仍交给框架StreamingResponse，不自行实现ASGI发送。
"""

import asyncio
import re
from collections.abc import AsyncIterator, Iterator
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from rdp.api._account_context import identity
from rdp.api._asgi import ASGIMessage, Receive, Send
from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.infra.diagnostics import DefectError
from rdp.jobs._file_parquet import ParquetPage
from rdp.jobs._file_video import VideoInfo, VideoQuery, VideoStream
from rdp.jobs.dataset_browser.schemas import DatasetId
from rdp.jobs.file_viewer import (
    FILE_CHUNK_BYTES,
    FileInfo,
    FilePage,
    FileQuery,
    FileSlice,
    FileViewerService,
    ParquetQuery,
)
from rdp.jobs.service import JobRequest

router = APIRouter(prefix="/api/datasets", tags=["files"])
# 50ms轮询首块前的断开事件；不等待转码总时限才清理。
_VIDEO_DISCONNECT_INTERVAL_S = 0.05
_Account = Annotated[AccountRequestContext, Depends(get_authenticated_context)]


def _service(request: Request) -> FileViewerService:
    """从启动装配取得查看器，不读取默认配置或向其他浏览模块增加存储能力。"""
    service = getattr(request.app.state, "file_viewer_service", None)
    if not isinstance(service, FileViewerService):
        raise DefectError()
    return service


@router.get("/{dataset_id}/files", response_model=FilePage, operation_id="list_dataset_files")
def list_dataset_files(
    request: Request, account: _Account, dataset_id: DatasetId, query: Annotated[FileQuery, Query()]
) -> FilePage:
    """列出规范入口已登记链接目标内的一页目录项。

    Args:
        request: 当前HTTP请求，仅取本应用已装配服务。
        account: 已登录且完成改密的任意账号。
        dataset_id: 永久数据集编号，遵循已合并DatasetId约束。
        query: 链接名、相对路径与分页，offset从0起，limit最大500。

    Returns:
        200目录页；修改时刻UTC，大小为字节，has_more表示还能翻页。

    Raises:
        DatasetQueryError: 越界路径、非登记链接或非目录，422。
        DatasetNotFoundError: 编号没有唯一规范入口，404。
        ExternalError: 离线、超时或I/O失败，502和五段诊断。
        DefectError: 查看器未装配，500；认证错误沿用全局边界。

    Side Effects:
        只读导航清单及选定存储目录，不提交作业或修改文件。

    Time Semantics:
        同步工作线程调用；挂载和目录读取共用配置超时，跨页允许变化。
    """
    job_request = JobRequest(identity(account), account.now, account.audit)
    return _service(request).list_files(job_request, dataset_id, query)


@router.get(
    "/{dataset_id}/file",
    response_class=Response,
    operation_id="read_dataset_file",
    responses={
        200: {
            "description": "普通文件原字节；被动媒体可内联，其他二进制附件下载",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
        206: {
            "description": "单段bytes范围；Content-Range为bytes start-end/total",
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        },
        416: {"description": "范围不可满足；Content-Range为bytes */total"},
    },
)
def read_dataset_file(
    request: Request, account: _Account, dataset_id: DatasetId, query: Annotated[FileQuery, Query()]
) -> Response:
    """返回登记链接目标内普通文件的原字节。

    Args:
        request: 当前请求，读取应用级查看器。
        account: 任意已登录且完成改密的账号。
        dataset_id: 永久编号。
        query: 单分量链接名和目标内相对文件路径。

    Returns:
        200原字节或206单段Range，提供Content-Length、Accept-Ranges和Content-Range；
        不可满足或不支持的Range返回416及bytes */总长。禁止缓存和MIME嗅探。

    Raises:
        DatasetQueryError: 越界、非文件或太大，422。
        DatasetNotFoundError: 数据集没有规范入口，404。
        ExternalError: 离线或超时，502；认证失败沿用全局边界。
        DefectError: 服务未正确装配，500。

    Side Effects:
        只读文件，每块逐段安全打开并核对同一文件身份，不写存储。

    Time Semantics:
        预检和每个1MiB块各受M0预算控制；首块失败仍返回502五段诊断。
        响应开始后存储失败只能中止流，不能更改已发送状态码；无重试。
    """
    service = _service(request)
    actor = JobRequest(identity(account), account.now, account.audit)
    info = service.file_info(actor, dataset_id, query)
    span = _range(request.headers.get("range"), info.size_bytes)
    headers = {
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Accept-Ranges": "bytes",
        "Content-Security-Policy": "sandbox; default-src 'none'",
    }
    if span is None:
        return Response(
            status_code=416, headers=headers | {"Content-Range": f"bytes */{info.size_bytes}"}
        )
    start, end = span
    length = max(0, end - start + 1)
    headers["Content-Length"] = str(length)
    partial = "range" in request.headers
    if partial:
        headers["Content-Range"] = f"bytes {start}-{end}/{info.size_bytes}"
    if info.media_type == "application/octet-stream":
        headers["Content-Disposition"] = "attachment"
    first = (
        service.read_file(
            actor,
            dataset_id,
            FileSlice(query=query, info=info, offset=start, length=min(length, FILE_CHUNK_BYTES)),
        )
        if length
        else b""
    )
    return StreamingResponse(
        _stream(service, actor, dataset_id, (query, info, start, end, first)),
        status_code=206 if partial else 200,
        media_type=info.media_type,
        headers=headers,
    )


def _range(value: str | None, size: int) -> tuple[int, int] | None:
    """仅支持单段bytes范围；无效或不可满足范围按HTTP规范返回416。"""
    if value is None:
        return 0, size - 1
    match = re.fullmatch(r"bytes=([0-9]*)-([0-9]*)", value)
    if match is None or size == 0:
        return None
    left, right = match.groups()
    # HTTP头有界解析；超长十进制不交给int，避免触发Python的整数转换限制。
    if not (left or right) or max(len(left), len(right)) > 20:
        return None
    if not left:
        count = int(right)
        return (max(0, size - count), size - 1) if count else None
    start, end = int(left), min(int(right), size - 1) if right else size - 1
    return (start, end) if start <= end and start < size else None


def _stream(
    service: FileViewerService,
    actor: JobRequest,
    dataset_id: str,
    transfer: tuple[FileQuery, FileInfo, int, int, bytes],
) -> Iterator[bytes]:
    """先发已经预读的首块，后续块逐个受超时与文件身份约束，不预取整个视频。"""
    query, info, start, end, first = transfer
    if first:
        yield first
    offset = start + len(first)
    while offset <= end:
        content = service.read_file(
            actor,
            dataset_id,
            FileSlice(
                query=query,
                info=info,
                offset=offset,
                length=min(FILE_CHUNK_BYTES, end - offset + 1),
            ),
        )
        yield content
        offset += len(content)


@router.get(
    "/{dataset_id}/parquet", response_model=ParquetPage, operation_id="preview_dataset_parquet"
)
def preview_dataset_parquet(
    request: Request,
    account: _Account,
    dataset_id: DatasetId,
    query: Annotated[ParquetQuery, Query()],
) -> ParquetPage:
    """预览登记链接内parquet结构和有界数据页。

    Args:
        request: 当前HTTP请求，仅取已装配查看器。
        account: 已登录且完成改密的账号。
        dataset_id: 数据集永久编号。
        query: 链接名、相对路径、行offset与limit；limit最大200。

    Returns:
        200结构和分页；单元格最多1024字符并标记截断，超过2GiB只返回结构与计数。

    Raises:
        DatasetQueryError: 非法路径、分页或损坏文件，422。
        DatasetNotFoundError: 数据集不存在，404。
        ExternalError: 存储离线或读取超时，502五段诊断。
        DefectError: 查看器未装配，500；认证失败沿用全局边界。

    Side Effects:
        只读选定文件需要的行组，不写存储或提交作业。

    Time Semantics:
        同步工作线程中执行，整个读取受配置的存储秒级预算限制。
    """
    return _service(request).parquet_page(
        JobRequest(identity(account), account.now, account.audit), dataset_id, query
    )


@router.get(
    "/{dataset_id}/video-info", response_model=VideoInfo, operation_id="probe_dataset_video"
)
def probe_dataset_video(
    request: Request, account: _Account, dataset_id: DatasetId, query: Annotated[FileQuery, Query()]
) -> VideoInfo:
    """探测登记视频的编码与总时长，供浏览器选择播放方式。

    Args:
        request: 当前HTTP请求，读取本应用查看器。
        account: 已登录且完成改密的账号。
        dataset_id: 数据集永久编号。
        query: 链接名与目标内相对普通文件路径。

    Returns:
        200视频编码与以秒计的总时长。

    Raises:
        DatasetQueryError: 路径非法或不是普通文件，422。
        DatasetNotFoundError: 编号不存在，404。
        ExternalError: 存储离线、探测失败或超时，502五段诊断。
        DefectError: 应用未装配查看器，500；认证沿用全局边界。

    Side Effects:
        只读安全描述符，启动并回收ffprobe，不修改源文件。

    Time Semantics:
        总时长以视频开始为零点；探测共用配置的存储访问预算。
    """
    return _service(request).video_info(
        JobRequest(identity(account), account.now, account.audit), dataset_id, query
    )


@router.get(
    "/{dataset_id}/video",
    response_class=Response,
    operation_id="transcode_dataset_video",
    responses={
        200: {
            "description": "H.264分片MP4",
            "content": {"video/mp4": {"schema": {"type": "string", "format": "binary"}}},
        },
        429: {"description": "两路转码均已占用，五段诊断"},
    },
)
async def transcode_dataset_video(
    request: Request,
    account: _Account,
    dataset_id: DatasetId,
    query: Annotated[VideoQuery, Query()],
) -> Response:
    """把登记视频的选定时间段转为浏览器可播放的H.264分片MP4。

    Args:
        request: 当前HTTP请求，取得本应用查看器。
        account: 已登录且完成改密的账号。
        dataset_id: 数据集永久编号。
        query: 登记链接、相对文件路径、起点秒数与片长；默认60秒，最多300秒。

    Returns:
        200 video/mp4流，禁止缓存；不承诺Content-Length，不支持字节Range。

    Raises:
        DatasetQueryError: 路径或时间参数非法，422。
        DatasetNotFoundError: 数据集不存在，404。
        VideoBusyError: 两路转码均已占用，429五段诊断。
        ExternalError: 工具缺失、编码器不可用、超时或转码失败，首块前返回502诊断。
        DefectError: 服务装配错误，500；认证沿用全局边界。

    Side Effects:
        只读源描述符，启动ffmpeg；完成、断开或超时均杀进程并释放许可，不写产物。

    Time Semantics:
        start_s相对于源视频开始；单次转码总时限120秒。首块后失败中止流，不能更改已发状态。
    """
    pending = asyncio.create_task(
        asyncio.to_thread(
            _service(request).video_stream,
            JobRequest(identity(account), account.now, account.audit),
            dataset_id,
            query,
        )
    )
    stream: VideoStream | None = None
    try:
        stream = await _while_connected(request, pending)
        first = await _while_connected(request, asyncio.create_task(asyncio.to_thread(stream.read)))
    except BaseException:
        if stream is not None:
            stream.close()
        else:
            pending.add_done_callback(_close_late_video)
        raise
    background = BackgroundTasks()
    background.add_task(stream.close)
    return _VideoResponse(
        stream,
        _video_chunks(stream, first),
        background=background,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


async def _video_chunks(stream: VideoStream, first: bytes) -> AsyncIterator[bytes]:
    """取消时finally同步杀进程，使等待pipe的线程立即解除，不让断开客户端留下转码。"""
    try:
        if first:
            yield first
        while block := await asyncio.to_thread(stream.read):
            yield block
    finally:
        stream.close()


async def _while_connected[T](request: Request, task: asyncio.Task[T]) -> T:
    """等待线程结果时检查断开；不取消工作线程，由调用方关闭迟到的资源。"""
    while not task.done():
        if await request.is_disconnected():
            task.add_done_callback(_consume_video_result)
            raise asyncio.CancelledError()
        await asyncio.wait({task}, timeout=_VIDEO_DISCONNECT_INTERVAL_S)
    return task.result()


def _close_late_video(task: asyncio.Task[VideoStream]) -> None:
    """启动阶段已经断开时，关闭迟到进程；取出失败以免后台Task异常无人读取。"""
    if not task.cancelled() and task.exception() is None:
        task.result().close()


class _VideoResponse(StreamingResponse):
    """无论ASGI发送失败还是取消，都在最外层finally关闭工具，不依赖生成器GC。"""

    def __init__(
        self,
        stream: VideoStream,
        content: AsyncIterator[bytes],
        background: BackgroundTasks,
        headers: dict[str, str],
    ) -> None:
        """把进程生命周期绑定到响应的发送边界。"""
        self._video_stream = stream
        super().__init__(content, media_type="video/mp4", background=background, headers=headers)

    async def __call__(self, scope: ASGIMessage, receive: Receive, send: Send) -> None:
        """包括ASGI2.4的send抛OSError在内，所有退出都立即回收ffmpeg。"""
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._video_stream.close()


def _consume_video_result[T](task: asyncio.Task[T]) -> None:
    """断开后读取线程仍会短暂运行，取出迟到异常以免成为无人处理的Task失败。"""
    if not task.cancelled():
        _ = task.exception()
