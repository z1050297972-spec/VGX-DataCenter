"""原文件只读HTTP边界（M1.5-01），沿用全局登录与五段诊断。

不使用FileResponse自行按路径打开：查看器需逐分量防换链、O_NOATIME和每块存储超时。
单段Range按HTTP字节位置计算，原字节传输仍交给框架StreamingResponse，不自行实现ASGI发送。
"""

import re
from collections.abc import Iterator
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse

from rdp.api._account_context import identity
from rdp.api.account_auth import AccountRequestContext, get_authenticated_context
from rdp.infra.diagnostics import DefectError
from rdp.jobs.dataset_browser.schemas import DatasetId
from rdp.jobs.file_viewer import (
    FILE_CHUNK_BYTES,
    FileInfo,
    FilePage,
    FileQuery,
    FileSlice,
    FileViewerService,
)
from rdp.jobs.service import JobRequest

router = APIRouter(prefix="/api/datasets", tags=["files"])
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
