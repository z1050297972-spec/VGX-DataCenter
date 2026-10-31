"""原文件只读查看（领域层，M1.5-01），唯一允许Web读存储根的模块。

复用导航描述符边界、标准库分页和M0存储超时；不写导航、数据或索引。
每次操作在M0隔离线程内完成，迟到结果不发布；内核阻塞不能强杀，最多保留四个访问槽。
"""

import logging
import mimetypes
import os
import stat
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Engine

from rdp.accounts.service import authorize_job_actor
from rdp.infra.config import StorageConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.db.validation import invalid_field
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)
from rdp.infra.storage import MountInspector, OfflineReason, StorageAccessChecker
from rdp.jobs import _file_parquet, _file_video
from rdp.jobs.dataset_browser.errors import DatasetNotFoundError, DatasetQueryError
from rdp.jobs.datasets import _io, _json
from rdp.jobs.datasets._readonly import open_fd
from rdp.jobs.datasets._storage_paths import inspect_path
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.service import JobRequest

logger = logging.getLogger(__name__)
_T = TypeVar("_T")
# M1.5-01规定单页上限500；四个并发槽限制离线NAS遗留线程数量，避免拖垮Web。
FILE_PAGE_LIMIT = 500
_ACCESS_SLOTS = BoundedSemaphore(4)
_ACCESS_DEADLINE: ContextVar[float | None] = ContextVar("file_viewer_deadline", default=None)


# 每个流式块1MiB，避免视频按Range上界一次分配；文本上限复用M1-01的32MiB。
FILE_CHUNK_BYTES = 1024 * 1024


class FileInfo(BaseModel):
    """同一次打开观察到的文件身份；stamp用于阻止串接变化前后的内容。"""

    size_bytes: int
    media_type: str
    stamp: tuple[int, int, int, int, int]


class FileQuery(BaseModel):
    """查看器路径和分页输入；路径相对于当前登记链接目标。"""

    model_config = ConfigDict(extra="forbid")
    link_name: str = Field(min_length=1, max_length=255)
    path: str = Field(default="", max_length=4096)
    offset: int = Field(default=0, ge=0, le=10_000_000)
    limit: int = Field(default=100, ge=1, le=FILE_PAGE_LIMIT)


class ParquetQuery(FileQuery):
    """parquet行分页；公开声明与运行时共用200行上限，默认也为200行。"""

    limit: int = Field(
        default=_file_parquet.PARQUET_PAGE_LIMIT, ge=1, le=_file_parquet.PARQUET_PAGE_LIMIT
    )


class FileSlice(BaseModel):
    """一次有界块读取，offset与length均以字节计，info来自本次响应的预检。"""

    query: FileQuery
    info: FileInfo
    offset: int = Field(ge=0)
    length: int = Field(ge=0, le=FILE_CHUNK_BYTES)


class FileItem(BaseModel):
    """直接目录项；大小为字节，修改时刻为UTC，不把软链接当可直接预览的文件。"""

    name: str
    kind: str
    size_bytes: int
    modified_at: datetime


class FilePage(BaseModel):
    """最多500项的目录页；不为得到总数而全量枚举目录。"""

    items: tuple[FileItem, ...]
    offset: int
    limit: int
    has_more: bool


def _problem(message: str, category: DiagnosticCategory) -> Diagnostic:
    """把路径拒绝或存储失败说明放在对应五段诊断中，不套用数据库校验文案。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="原文件只读查看",
        source="平台",
        objects=(),
        rule="FILE_VIEWER_STORAGE"
        if category is DiagnosticCategory.EXTERNAL
        else "FILE_VIEWER_PATH",
        actual=message,
        expected="已登记链接内的只读路径且存储根在线",
        consequence="本次读取停止，不修改任何文件",
        next_step="检查存储挂载和读取权限后重试"
        if category is DiagnosticCategory.EXTERNAL
        else "选择登记链接下的有效相对路径；清单有变化时重新扫描",
    )


def _reject(message: str) -> DatasetQueryError:
    """生成输入拒绝，不回显任意原始路径。"""
    return DatasetQueryError((_problem(message, DiagnosticCategory.INPUT),))


def _external(message: str) -> ExternalError:
    """生成能指导存储故障恢复的五段诊断。"""
    return ExternalError((_problem(message, DiagnosticCategory.EXTERNAL),))


class _AccessSlot:
    """只读操作的并发许可；正常结束或已知失败恰好归还一次，超时内核读取保留许可。"""

    def __init__(self) -> None:
        """非阻塞取得一个只读访问槽，保留幂等归还状态。"""
        self._guard = Lock()
        self._released = False
        if not _ACCESS_SLOTS.acquire(blocking=False):
            raise _external("存储访问槽已满，请恢复存储后重试；挂载检查超时占槽时需重启Web")

    def release(self) -> None:
        """允许M0错误边界和回调清理共用此入口，避免重复归还许可。"""
        with self._guard:
            if not self._released:
                self._released = True
                _ACCESS_SLOTS.release()


def _validate(query: FileQuery) -> None:
    """拒绝绝对路径、穿越、NUL和非单分量链接名；不规范化用户的穿越输入。"""
    if (
        query.link_name in {".", ".."}
        or "/" in query.link_name
        or "\x00" in query.link_name
        or Path(query.path).is_absolute()
        or ".." in query.path.split("/")
        or "\x00" in query.path
    ):
        raise _reject("需要链接目标内不含..的相对路径")


def _checkpoint() -> None:
    """在独立访问线程内检查共同截止，迟到I/O返回后不再开始下一次读取。"""
    deadline = _ACCESS_DEADLINE.get()
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("原文件只读访问超时")


def _target(
    engine: Engine, nav_root: Path, request: JobRequest, dataset_id: str, name: str
) -> Path:
    """重验身份后读取规范清单，只接受已登记且实际链接与声明一致的目标。"""
    with session_scope(engine, read_only=True) as session:
        authorize_job_actor(session, request.identity, now=request.now)
        row = session.get(DatasetRow, dataset_id)
        entry = row.canonical_entry_path if row else None
    if entry is None:
        raise DatasetNotFoundError(
            invalid_field("dataset_id", "有唯一规范入口的数据集").diagnostics
        )
    # 索引只用于定位；目标取当前导航JSON，避免改指向后继续暴露旧数据。
    import json

    try:
        with _io.directory(nav_root / entry) as descriptor:
            content = _io.read_file(descriptor, "原始路径.json", _checkpoint)
            document = _json.object_value(json.loads(content))
            if document.get("dataset_id") != dataset_id:
                raise _reject("规范清单身份不一致，请重新扫描")
            links: object = document.get("links")
            if not isinstance(links, list):
                raise _reject("规范清单链接不可用")
            matches = [
                cast(dict[str, object], link)
                for link in cast(list[object], links)
                if isinstance(link, dict) and cast(dict[str, object], link).get("name") == name
            ]
            if len(matches) != 1:
                raise _reject("需要规范入口已登记的唯一链接")
            target: object = matches[0].get("source_path")
            if not isinstance(target, str) or os.readlink(name, dir_fd=descriptor) != target:
                raise _reject("链接已变化或与登记不符，请重新扫描")
    except (ValueError, OSError) as error:
        raise _reject("导航链接或清单不可读，请重新扫描") from error
    path = Path(target)
    if not path.is_absolute() or ".." in path.parts or "\x00" in target:
        raise _reject("登记目标必须为无穿越的绝对路径")
    return path


def _safe_open(path: Path, root: Path, relative: str) -> int:
    """先有限解析再逐段O_NOFOLLOW打开，防止检查后换链造成越界读取。"""
    _checkpoint()
    base = inspect_path(path, root)
    if base.exists is not True:
        raise _reject("链接目标不存在或越出存储根")
    observed = inspect_path(base.resolved / relative, base.resolved)
    if observed.exists is not True:
        raise _reject("文件不存在或软链接越出链接目标")
    descriptor = open_fd(Path("/"), directory=True)
    try:
        for part in observed.resolved.parts[1:]:
            _checkpoint()
            child = open_fd(Path(part), dir_fd=descriptor, nonblocking=True)
            os.close(descriptor)
            descriptor = child
        result = descriptor
        descriptor = -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _list(path: Path, root: Path, query: FileQuery) -> FilePage:
    """按文件系统枚举顺序取一页，不排序或缓存百万目录项；软链接只读自身元数据。"""
    descriptor = _safe_open(path, root, query.path)
    items: list[FileItem] = []
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise _reject("所选路径不是目录")
        with os.scandir(descriptor) as entries:
            for index, entry in enumerate(entries):
                _checkpoint()
                if index < query.offset:
                    continue
                if len(items) == query.limit:
                    return FilePage(
                        items=tuple(items), offset=query.offset, limit=query.limit, has_more=True
                    )
                info = entry.stat(follow_symlinks=False)
                kind = "directory" if stat.S_ISDIR(info.st_mode) else "file"
                if stat.S_ISLNK(info.st_mode):
                    kind = "symlink"
                elif not stat.S_ISDIR(info.st_mode) and not stat.S_ISREG(info.st_mode):
                    kind = "special"
                items.append(
                    FileItem(
                        name=entry.name,
                        kind=kind,
                        size_bytes=info.st_size,
                        modified_at=datetime.fromtimestamp(info.st_mtime, UTC),
                    )
                )
        return FilePage(items=tuple(items), offset=query.offset, limit=query.limit, has_more=False)
    finally:
        os.close(descriptor)


class FileViewerService:
    """只读查看器依赖；不持有Session或写存储能力。"""

    def __init__(
        self, engine: Engine, nav_root: Path, mounts: MountInspector, options: StorageConfig
    ) -> None:
        """绑定查看器的数据库、导航根和访问预算。

        Args:
            engine: 已迁移的受管引擎，不转移所有权。
            nav_root: 绝对导航根，不含..。
            mounts: 已登记根及挂载身份只读检查器。
            options: 每次存储操作总超时，单位秒，沿用M0配置范围。

        Returns:
            无。

        Raises:
            无。

        Side Effects:
            仅保存依赖，不读文件或启动线程。

        Time Semantics:
            构造无等待；每次调用现场读取导航和挂载身份。
        """
        self.engine, self.nav_root = engine, nav_root
        self.mounts, self.options = mounts, options

    def list_files(self, request: JobRequest, dataset_id: str, query: FileQuery) -> FilePage:
        """列出当前登记链接目标中的一页直接目录项。

        Args:
            request: 可信身份、UTC时刻及审计上下文。
            dataset_id: 已入索引的永久编号。
            query: 单层链接名、相对路径及从零起的分页，单页1至500项。

        Returns:
            文件系统枚举顺序的目录页；空目录items为空，不计算完整总数。

        Raises:
            DatasetQueryError: 路径越界、清单不符或不是目录。
            DatasetNotFoundError: 数据集没有唯一规范入口。
            AuthenticationError: 会话失效。
            ExternalError: 存储根离线、超时、并发槽耗尽或I/O失败。
            DefectError: 依赖或回调结果违反内部契约。

        Side Effects:
            只读当前导航清单、链接自身及选定存储目录；使用O_NOATIME，EPERM退回普通读取。

        Time Semantics:
            每次现场读取；存储操作含挂载核对共用options.access_timeout_s秒；跨页允许目录变化。
        """
        return self._access(request, dataset_id, query, lambda path, root: _list(path, root, query))

    def file_info(self, request: JobRequest, dataset_id: str, query: FileQuery) -> FileInfo:
        """检查普通文件类型、大小和内容身份，尚不读取正文。

        Args:
            request: 当前可信账号身份、UTC时刻和审计上下文。
            dataset_id: 已索引的永久编号。
            query: 登记链接名与目标内相对文件路径。

        Returns:
            字节大小、受控媒体类型及设备/inode/大小/修改和变更时间组成的stamp。

        Raises:
            DatasetQueryError: 路径非法、不是普通文件或非图片/视频文件超过32MiB。
            DatasetNotFoundError: 数据集没有唯一规范入口。
            AuthenticationError: 当前会话失效。
            ExternalError: 存储离线或预检超时。
            DefectError: 内部装配违约。

        Side Effects:
            只读导航清单、链接及文件元数据，不读取正文或写缓存。

        Time Semantics:
            挂载核对和打开共用配置预算；后续每块按stamp拒绝变化。
        """
        return self._access(request, dataset_id, query, lambda path, root: _info(path, root, query))

    def read_file(self, request: JobRequest, dataset_id: str, part: FileSlice) -> bytes:
        """读取预检文件的一个有界块，拒绝变化的文件或登记目标。

        Args:
            request: 已认证账号请求；读取期间沿用同一次请求UTC时刻。
            dataset_id: 已索引永久编号。
            part: 预检身份、相对路径、非负字节偏移及最多1MiB的块长。

        Returns:
            恰好length字节的原始内容；length为0时为空，提前遇到EOF按读取失败处理。

        Raises:
            DatasetQueryError: 路径越界、登记不符或不是普通文件。
            DatasetNotFoundError: 规范入口不存在。
            AuthenticationError: 会话已撤销。
            ExternalError: 文件变化、存储离线、超时或读取失败。
            DefectError: 内部装配违约。

        Side Effects:
            只读导航和文件，每块打开后关闭，不保留跨响应描述符。

        Time Semantics:
            每块含挂载核对独立受配置秒级预算控制；无自动重试，变化后停止流。
        """
        return self._access(
            request, dataset_id, part.query, lambda path, root: _read_slice(path, root, part)
        )

    def parquet_page(
        self, request: JobRequest, dataset_id: str, query: FileQuery
    ) -> _file_parquet.ParquetPage:
        """读取parquet结构与一页有界文本，不读取无关行组。

        Args:
            request: 当前可信身份和UTC请求上下文。
            dataset_id: 已索引的数据集永久编号。
            query: 登记链接、相对文件路径和从零起的行偏移；limit为1至200行。

        Returns:
            列结构、总行数、行组数和最多200行；超过2GiB时schema_only为真且rows为空。

        Raises:
            DatasetQueryError: 路径非法、非普通文件、分页超过200行或parquet损坏。
            DatasetNotFoundError: 没有唯一规范入口。
            AuthenticationError: 当前会话失效。
            ExternalError: 存储离线、超时或I/O失败。
            DefectError: 内部依赖装配违约。

        Side Effects:
            只读导航和O_NOATIME打开的文件；EPERM沿用普通只读回退，不写缓存。

        Time Semantics:
            结构与分页共用配置的存储访问秒级预算；不缓存或重试。
        """
        if query.limit > _file_parquet.PARQUET_PAGE_LIMIT:
            raise DatasetQueryError(_reject("parquet单页最多200行").diagnostics)

        def read(path: Path, root: Path) -> _file_parquet.ParquetPage:
            descriptor = _safe_open(path, root, query.path)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise _reject("只能预览普通parquet文件")
            try:
                return _file_parquet.read_page(descriptor, query.offset, query.limit, _checkpoint)
            except (ValueError, TypeError) as error:
                raise _reject("parquet文件损坏或内容无法解析") from error

        return self._access(request, dataset_id, query, read)

    def video_info(
        self, request: JobRequest, dataset_id: str, query: FileQuery
    ) -> _file_video.VideoInfo:
        """探测登记视频的首个视频流编码与总时长。

        Args:
            request: 当前可信身份与UTC请求上下文。
            dataset_id: 已索引永久编号。
            query: 已登记链接名与目标内相对普通文件路径。

        Returns:
            编码名称和有限非负的总秒数。

        Raises:
            DatasetQueryError: 路径非法或不是普通文件。
            DatasetNotFoundError: 数据集没有唯一规范入口。
            AuthenticationError: 会话失效。
            ExternalError: 存储离线、超时、工具缺失或视频损坏。
            DefectError: 查看器装配违约。

        Side Effects:
            只读O_NOATIME文件描述符，启动并回收ffprobe，不写存储。

        Time Semantics:
            探测共用存储访问预算，子进程不超过剩余秒数且最多10秒，无重试。
        """
        return self._access(
            request,
            dataset_id,
            query,
            lambda path, root: cast(_file_video.VideoInfo, _video_open(path, root, query, None)),
        )

    def video_stream(
        self, request: JobRequest, dataset_id: str, query: _file_video.VideoQuery
    ) -> _file_video.VideoStream:
        """启动一个受限的H.264分片MP4流，由调用方在finally关闭。

        Args:
            request: 当前已认证身份与UTC请求上下文。
            dataset_id: 已索引的永久编号。
            query: 链接、相对文件路径、非负起点秒数与大于0且最多300秒的片长。

        Returns:
            已启动的流对象；调用方必须读取首块后才发送响应头，结束或断开时close。

        Raises:
            DatasetQueryError: 相对路径非法或非普通文件。
            DatasetNotFoundError: 没有唯一规范入口。
            AuthenticationError: 会话撤销。
            VideoBusyError: 两路转码许可已占满。
            ExternalError: 存储失败、工具或编码器不可用；读取流时也可能报告转码失败。
            DefectError: 内部装配违约。

        Side Effects:
            只读安全描述符，启动ffmpeg；关闭或120秒总时限杀进程归还许可，不写缓存。

        Time Semantics:
            起点和片长以源视频开始为零点；启动受存储预算，流总时限120秒，无自动重试。
        """
        location = FileQuery(link_name=query.link_name, path=query.path)
        return self._access(
            request,
            dataset_id,
            location,
            lambda path, root: cast(
                _file_video.VideoStream, _video_open(path, root, location, query)
            ),
        )

    def _access(
        self,
        request: JobRequest,
        dataset_id: str,
        query: FileQuery,
        action: Callable[[Path, Path], _T],
    ) -> _T:
        """用M0总预算执行一次操作，业务异常在调用线程抛出，不冒充适配器缺陷。"""
        started = time.monotonic()
        _validate(query)
        target = _target(self.engine, self.nav_root, request, dataset_id, query.link_name)
        root = next((item for item in self.mounts.roots if target.is_relative_to(item.path)), None)
        if root is None or target.is_relative_to(self.nav_root):
            raise _reject("目标必须在登记存储根内且不在导航层内")
        slot = _AccessSlot()
        results: list[_T | InputError | ExternalError] = []
        deadline = time.monotonic() + self.options.access_timeout_s

        def observe(_root: Path) -> None:
            token = _ACCESS_DEADLINE.set(deadline)
            try:
                results.append(action(target, root.path))
            except (InputError, ExternalError) as error:
                results.append(error)
            finally:
                _ACCESS_DEADLINE.reset(token)
                slot.release()

        try:
            status = StorageAccessChecker(self.mounts, self.options, observe).check(
                root.name, checkpoint=_checkpoint
            )
        except BaseException:
            # 身份查询等步骤在调用observe之前也可能失败；与回调finally共用幂等释放。
            slot.release()
            raise
        if not status.online:
            # 超时可能仍在内核阻塞，保留槽直到回调结束；挂载检查本身超时则保守占槽到重启。
            if status.reason is not OfflineReason.TIMEOUT:
                slot.release()
            raise _external(f"存储根离线：{status.reason}")
        if not results:
            raise DefectError()
        result = results[0]
        if isinstance(result, (InputError, ExternalError)):
            error = _identified_failure(result, dataset_id, query)
            raise error from result
        logger.debug(
            "原文件只读访问完成",
            extra={
                "fields": {
                    "dataset_id": dataset_id,
                    "storage_root": root.name,
                    "elapsed_s": max(0.0, time.monotonic() - started),
                }
            },
        )
        return result


def _metadata(descriptor: int, name: str) -> FileInfo:
    """只内联允许的被动媒体类型；HTML/SVG等主动内容作为附件下载，防止同源脚本。"""
    from rdp.jobs.datasets.catalog import MAX_DOCUMENT_BYTES

    _checkpoint()
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode):
        raise _reject("只能读取普通文件")
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    passive_images = {
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/avif",
    }
    if media not in passive_images and not media.startswith("video/"):
        # MIME登记随主机不同；未知类型可能是log/jsonl或无后缀文本，不能绕过32MiB上限。
        if info.st_size > MAX_DOCUMENT_BYTES:
            raise _reject("太大，请下载工具查看")
        if not media.startswith("text/") and media != "application/json":
            media = "application/octet-stream"
    return FileInfo(
        size_bytes=info.st_size,
        media_type=media,
        stamp=(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
    )


def _info(path: Path, root: Path, query: FileQuery) -> FileInfo:
    """预检与分块读取共用安全打开和元数据规则。"""
    descriptor = _safe_open(path, root, query.path)
    try:
        return _metadata(descriptor, query.path)
    finally:
        os.close(descriptor)


def _read_slice(path: Path, root: Path, part: FileSlice) -> bytes:
    """按位置读取同一文件身份，并在读取后复核，避免变动文件的混合响应。"""
    descriptor = _safe_open(path, root, part.query.path)
    try:
        if _metadata(descriptor, part.query.path) != part.info:
            raise OSError("文件已变化，请重新打开")
        content = bytearray()
        while len(content) < part.length:
            _checkpoint()
            block = os.pread(descriptor, part.length - len(content), part.offset + len(content))
            if not block:
                raise OSError("读取期间文件已截短，请重新打开")
            content.extend(block)
        if _metadata(descriptor, part.query.path) != part.info:
            raise OSError("读取期间文件已变化，请重新打开")
        return bytes(content)
    finally:
        os.close(descriptor)


def _video_open(
    path: Path, root: Path, location: FileQuery, query: _file_video.VideoQuery | None
) -> _file_video.VideoInfo | _file_video.VideoStream:
    """在既有路径边界内借出安全fd；迟到的启动结果在发布前关闭，防止超时泄漏。"""
    descriptor = _safe_open(path, root, location.path)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise _reject("视频输入必须是普通文件")
        deadline = _ACCESS_DEADLINE.get()
        remaining_s = (
            min(_file_video.TOOL_TIMEOUT_S, deadline - time.monotonic())
            if deadline is not None
            else _file_video.TOOL_TIMEOUT_S
        )
        if query is None:
            return _file_video.probe(descriptor, max(0.001, remaining_s))
        stream = _file_video.transcode(descriptor, query, max(0.001, remaining_s))
        try:
            _checkpoint()
        except BaseException:
            stream.close()
            raise
        return stream
    finally:
        os.close(descriptor)


def _identified_failure(
    error: InputError | ExternalError, dataset_id: str, query: FileQuery
) -> InputError | ExternalError:
    """在掌握请求身份的查看器边界补上数据集和相对路径，保留原异常类别与状态。"""
    identity = (
        DiagnosticObject(key="dataset_id", value=dataset_id),
        DiagnosticObject(key="link_name", value=query.link_name),
        DiagnosticObject(key="relative_path", value=query.path or "/"),
    )
    diagnostics = tuple(
        Diagnostic.model_validate(item.model_dump() | {"objects": (*item.objects, *identity)})
        for item in error.diagnostics
    )
    return type(error)(diagnostics)
