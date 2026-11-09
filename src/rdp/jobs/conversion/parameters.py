"""转换参数和输入选择（领域层，M4-03）；只查询索引，不访问存储根。

结构校验复用 Pydantic，数据块归属用现有 SQLAlchemy 索引，不另建转换索引。
"""

import re
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.db.validation import invalid_field
from rdp.jobs.datasets.models import DatasetRow, SourceRow
from rdp.jobs.errors import JobInputError
from rdp.tools.manifest import ToolManifest

# M4-03 的提交上限，限制命令参数及索引查询规模。
MAX_CONVERSION_SOURCES = 200


class InputSelection(BaseModel):
    """转换与清洗共用的索引选择，不读取数据盘。

    Attributes:
        dataset_id: 唯一规范入口的数据集编号，非空。
        source_ids: 按用户顺序的 1 至 200 个不同数据块编号。
        robot_model: 登记工具的型号键，非空。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    dataset_id: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=MAX_CONVERSION_SOURCES)
    robot_model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_sources(self) -> Self:
        """重复编号会重复处理同一输入，因此提交时拒绝。"""
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("数据块编号不得重复")
        return self


class ConversionParameters(InputSelection):
    """转换参数；输入规则复用 InputSelection，输出版本由工具模型补默认值。

    Attributes:
        output_format: 输出版本；None 由工具模型替换成清单首项。
        space_ratio_percent: 空间估算百分比，整数 0 至 1000，默认 25。
        space_reserve_gib: 空间预留偏置，0 至 1024 GiB，默认 1。
    """

    output_format: str | None = None
    # M4-07 实测产物/输入约 0.13，默认 25% 约为两倍。
    space_ratio_percent: int = Field(default=25, strict=True, ge=0, le=1000)
    # M4-07 沿用 M2 的 1 GiB 默认余量。
    space_reserve_gib: float = Field(default=1, ge=0, le=1024)


def tool_parameters(manifest: ToolManifest) -> type[ConversionParameters]:
    """为一个工具建立带型号与默认输出版本约束的参数模型。

    Args:
        manifest: 启动时已校验的工具清单。

    Returns:
        独立模型类；输出版本省略时取清单首项。

    Raises:
        无；调用返回模型时，非法型号或版本由Pydantic报告ValidationError。

    Side Effects:
        无；不读取工具程序或数据库。

    Time Semantics:
        模型约束是启动快照；执行前重新校验当前清单。
    """

    class _ToolParameters(ConversionParameters):
        """闭包保存单工具约束，不使用可变全局登记。"""

        @model_validator(mode="after")
        def _tool_choices(self) -> Self:
            """先补默认版本，再验证最终生效的两项选择。"""
            version = (
                manifest.io.output_versions[0] if self.output_format is None else self.output_format
            )
            if (
                self.robot_model not in manifest.models
                or version not in manifest.io.output_versions
            ):
                raise ValueError("型号或输出版本不在工具清单中")
            return self.model_copy(update={"output_format": version})

    return _ToolParameters


def selected_inputs(session: Session, parameters: InputSelection) -> tuple[Path, ...]:
    """按用户顺序读取同一规范入口下的mcap数据块位置。

    Args:
        session: 调用方管理的短数据库事务。
        parameters: 已通过结构校验的转换或清洗输入选择，数据块至多200项。

    Returns:
        与source_ids逐项对应的绝对路径元组；仅为索引值，不表示文件在线。

    Raises:
        JobInputError: 数据集无唯一规范入口，数据块不属于它、重复登记或格式不是mcap。
        ExternalError: 数据库访问失败，由受管会话边界转换。

    Side Effects:
        无（只读数据库索引，不解析路径或读取存储根）。

    Time Semantics:
        同一事务快照；提交和执行时分别核对，避免排队期间索引变化被忽略。
    """
    dataset = session.get(DatasetRow, parameters.dataset_id)
    if dataset is None or dataset.canonical_entry_path is None:
        raise JobInputError(invalid_field("dataset_id", "具有唯一规范入口的数据集").diagnostics)
    rows = tuple(
        session.scalars(
            select(SourceRow).where(
                SourceRow.entry_path == dataset.canonical_entry_path,
                SourceRow.source_id.in_(parameters.source_ids),
            )
        )
    )
    by_id = {row.source_id: row for row in rows}
    if (
        len(rows) != len(parameters.source_ids)
        or len(by_id) != len(rows)
        or any(row.format != "mcap" for row in rows)
    ):
        raise JobInputError(
            invalid_field("source_ids", "全部属于该数据集且格式为mcap的数据块").diagnostics
        )
    return tuple(Path(by_id[identifier].direct_path) for identifier in parameters.source_ids)


def conversion_type_name(tool_name: str) -> str:
    """把工具登记名转换为永久作业类型键。

    Args:
        tool_name: 工具清单名称，ASCII小写字母、数字和可选连字符。

    Returns:
        convert_前缀加去掉非字母数字后的名称。

    Raises:
        无；不存在或非法的最终类型键由作业提交统一拒绝。

    Side Effects:
        无。

    Time Semantics:
        纯字符串转换，无时钟或等待。
    """
    return "convert_" + re.sub("[^a-z0-9]", "", tool_name)
