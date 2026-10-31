"""查看器的parquet适配器（M1.5-04）；只消费安全描述符，不接受或自行打开路径。

标准库不解析parquet，使用已批准的pyarrow；分页用其iter_batches，避免整表加载。
pyarrow没有随包提供类型声明，局部Protocol只描述本适配器实际使用的只读接口。
"""

import json
import os
from collections.abc import Callable, Iterable, Iterator
from importlib import import_module
from typing import BinaryIO, Protocol, cast

from pydantic import BaseModel

# 工单M1.5-04：2GiB以上仅看结构；单页200行，单元格最多1024字符。
PARQUET_MAX_BYTES = 2 * 1024**3
PARQUET_PAGE_LIMIT = 200
PARQUET_CELL_CHARS = 1024


class ParquetColumn(BaseModel):
    """按文件声明顺序返回的列名与Arrow类型。"""

    name: str
    type: str


class ParquetCell(BaseModel):
    """有界显示文本；truncated明确表示原值尚有未展示内容。"""

    text: str
    truncated: bool = False


class ParquetPage(BaseModel):
    """parquet结构、精确计数与分页；行内单元格顺序与columns相同。"""

    columns: list[ParquetColumn]
    total_rows: int
    row_groups: int
    offset: int
    limit: int
    rows: list[list[ParquetCell]]
    has_more: bool
    schema_only: bool


class _Field(Protocol):
    name: str
    type: object


class _RowGroup(Protocol):
    num_rows: int


class _Metadata(Protocol):
    num_rows: int
    num_row_groups: int

    def row_group(self, index: int) -> _RowGroup:
        """取得第index个行组的计数。"""
        ...


class _Batch(Protocol):
    num_rows: int

    def to_pylist(self) -> list[dict[str, object]]:
        """把有界批次转换成显示值。"""
        ...

    def slice(self, offset: int, length: int) -> "_Batch":
        """截取批次中需要的行。"""
        ...


class _ParquetFile(Protocol):
    metadata: _Metadata
    schema_arrow: Iterable[_Field]

    def iter_batches(self, *, batch_size: int, row_groups: list[int]) -> Iterator[_Batch]:
        """只解码选定行组，每批有固定行数上界。"""
        ...


class _ParquetModule(Protocol):
    def ParquetFile(self, source: BinaryIO) -> _ParquetFile:  # noqa: N802 # 理由：匹配pyarrow公开接口。
        """用调用方提供的只读文件对象解析结构。"""
        ...


def _cell(value: object) -> ParquetCell:
    """用有界文本显示标量和嵌套对象；二进制只显示长度，避免放大响应。"""
    if isinstance(value, bytes):
        return ParquetCell(text=f"<binary: {len(value)} bytes>")
    if isinstance(value, str):
        return ParquetCell(
            text=value[:PARQUET_CELL_CHARS], truncated=len(value) > PARQUET_CELL_CHARS
        )
    text = ""
    for chunk in json.JSONEncoder(ensure_ascii=False, default=str).iterencode(value):
        text += chunk[: PARQUET_CELL_CHARS + 1 - len(text)]
        if len(text) > PARQUET_CELL_CHARS:
            break
    return ParquetCell(text=text[:PARQUET_CELL_CHARS], truncated=len(text) > PARQUET_CELL_CHARS)


def read_page(
    descriptor: int, offset: int, limit: int, checkpoint: Callable[[], None]
) -> ParquetPage:
    """接管描述符，在同一存储访问预算内读取结构和需要的行组。"""
    with os.fdopen(descriptor, "rb") as stream:
        module = cast(_ParquetModule, cast(object, import_module("pyarrow.parquet")))
        file = module.ParquetFile(stream)
        checkpoint()
        metadata = file.metadata
        columns = [
            ParquetColumn(name=field.name, type=str(field.type)) for field in file.schema_arrow
        ]
        schema_only = os.fstat(stream.fileno()).st_size > PARQUET_MAX_BYTES
        rows: list[list[ParquetCell]] = []
        if not schema_only:
            rows = _rows(file, columns, offset, limit, checkpoint)
        return ParquetPage(
            columns=columns,
            total_rows=metadata.num_rows,
            row_groups=metadata.num_row_groups,
            offset=offset,
            limit=limit,
            rows=rows,
            has_more=not schema_only and offset + len(rows) < metadata.num_rows,
            schema_only=schema_only,
        )


def _rows(
    file: _ParquetFile,
    columns: list[ParquetColumn],
    offset: int,
    limit: int,
    checkpoint: Callable[[], None],
) -> list[list[ParquetCell]]:
    """跳过无交集行组；每批最多200行，不为翻页物化整个行组。"""
    rows: list[list[ParquetCell]] = []
    skipped = 0
    for index in range(file.metadata.num_row_groups):
        checkpoint()
        count = file.metadata.row_group(index).num_rows
        if skipped + count <= offset:
            skipped += count
            continue
        for batch in file.iter_batches(batch_size=PARQUET_PAGE_LIMIT, row_groups=[index]):
            checkpoint()
            start = max(0, offset - skipped)
            if start < batch.num_rows:
                page = batch.slice(start, min(limit - len(rows), batch.num_rows - start))
                rows.extend(
                    [_cell(row[column.name]) for column in columns] for row in page.to_pylist()
                )
            skipped += batch.num_rows
            if len(rows) == limit:
                return rows
    return rows
