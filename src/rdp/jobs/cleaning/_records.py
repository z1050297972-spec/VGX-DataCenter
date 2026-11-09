"""用 mcap StreamReader 保持物理记录顺序，限制记录及解压块大小。

SDK 默认整块解压且没有解压尺寸限制；改用已批准的 zstandard/lz4 流读取上限，
再把块内记录交回 SDK。没有自行实现 MCAP 格式解析。
"""

import io
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from typing import BinaryIO, cast

import lz4.frame  # pyright: ignore[reportMissingTypeStubs]  # 已批准的 lz4 没有类型存根，调用边界在下方收窄。
import zstandard
from mcap.records import Chunk, McapRecord
from mcap.stream_reader import StreamReader

# 单记录和解压后单块最多 64 MiB，避免损坏长度或压缩炸弹耗尽 worker 内存。
MAX_RECORD_BYTES = 64 * 1024 * 1024


class BoundedReader(io.BufferedReader):
    """给 SDK 的底层 read 加上界，防止记录内部伪造长度绕过 record_size_limit。"""

    def read(self, size: int | None = -1) -> bytes:
        """只允许有明确上限的读取。"""
        if size is None or size < 0 or size > MAX_RECORD_BYTES:
            raise ValueError("MCAP 读取请求超过 64 MiB 安全上限")
        return super().read(size)


def records(stream: BinaryIO) -> Iterator[McapRecord]:
    """线性扫描数据与摘要，不按索引或消息时间排序，不积累跨块消息原文。"""
    reader = StreamReader(stream, emit_chunks=True, record_size_limit=MAX_RECORD_BYTES)
    for record in reader.records:
        if isinstance(record, Chunk):
            data = _decompress(record)
            with io.BytesIO(data) as chunk_stream:
                nested = StreamReader(
                    chunk_stream,
                    skip_magic=True,
                    emit_chunks=True,
                    record_size_limit=MAX_RECORD_BYTES,
                ).records
                while chunk_stream.tell() < len(data):
                    yield next(nested)
        else:
            yield record


def _decompress(chunk: Chunk) -> bytes:
    """在解压流上读 cap+1 字节，不能仅信任声明的 uncompressed_size。"""
    if chunk.uncompressed_size > MAX_RECORD_BYTES:
        raise ValueError("MCAP 解压块超过 64 MiB 安全上限")
    if chunk.compression == "zstd":
        with zstandard.ZstdDecompressor().stream_reader(chunk.data) as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
    elif chunk.compression == "lz4":
        # 第三方函数没有完整注解，这里只使用其二进制文件对象上下文协议。
        open_lz4 = cast(
            Callable[[io.BytesIO, str], AbstractContextManager[BinaryIO]], lz4.frame.open
        )
        with open_lz4(io.BytesIO(chunk.data), "rb") as stream:
            data = stream.read(MAX_RECORD_BYTES + 1)
    elif chunk.compression == "":
        data = chunk.data
    else:
        raise ValueError("不支持的 MCAP 压缩格式")
    if len(data) > MAX_RECORD_BYTES or len(data) != chunk.uncompressed_size:
        raise ValueError("MCAP 解压大小超限或与声明不符")
    return data
