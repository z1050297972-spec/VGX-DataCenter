"""转换参数和输入选择（领域层，M4-03）；只查询索引，不访问存储根。

结构校验复用 Pydantic，数据块归属用现有 SQLAlchemy 索引，不另建转换索引。
"""

import re
from pathlib import Path
from typing import Annotated, ClassVar, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.validation import invalid_field
from rdp.jobs.cleaning._g2 import validate_paths
from rdp.jobs.conversion._output_storage import select_root
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
        input_format: 工具参数类保存的清单输入格式，不接受请求传入、不写入作业 JSON。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    input_format: ClassVar[str]
    dataset_id: str = Field(min_length=1)
    source_ids: list[str] = Field(min_length=1, max_length=MAX_CONVERSION_SOURCES)
    robot_model: str = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_sources(self) -> Self:
        """重复编号会重复处理同一输入，因此提交时拒绝。"""
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValueError("数据块编号不得重复")
        return self


class EpisodeSelection(BaseModel):
    """预览段的稳定身份；两个编号均为从零起的整数。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    file_index: int = Field(strict=True, ge=0)
    segment_index: int = Field(strict=True, ge=0)


class ConversionOptions(BaseModel):
    """从预览发起转换的最终选择；空剔除列表表示全部保留，不重新套默认。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    output_root: str | None = Field(default=None, min_length=1)
    output_format: str | None = None
    # 25% 是 MCAP 历史默认；工具模型按清单补齐省略值，显式给出的 25 不能被覆盖。
    space_ratio_percent: int = Field(default=25, strict=True, ge=0, le=1000)
    space_reserve_gib: float = Field(default=1, ge=0, le=1024)
    excluded_files: list[Annotated[int, Field(strict=True, ge=0)]] = Field(default_factory=list)
    excluded_episodes: list[EpisodeSelection] = Field(default_factory=list)


class ConversionParameters(InputSelection, ConversionOptions):
    """转换参数；输入规则复用 InputSelection，输出版本由工具模型补默认值。

    Attributes:
        output_root: 已登记输出根的稳定名称；新提交时补齐并持久化。
        output_roots: 登记时注入的根快照，不接受请求传入。
        cleaning_preview_job_id: 成功预览编号；None 仅用于读取历史记录，执行时拒绝。
        excluded_files: 最终剔除的 file_index 列表，空列表全部保留。
        excluded_episodes: 最终剔除段的稳定预览身份，空列表全部保留。
        output_format: 输出版本；None 由工具模型替换成清单首项。
        space_ratio_percent: 空间估算百分比，整数 0 至 1000，省略时取清单默认值。
        space_reserve_gib: 空间预留偏置，0 至 1024 GiB，默认 1。
    """

    output_roots: ClassVar[tuple[StorageRootConfig, ...] | None] = None

    # 历史作业没有预览编号仍可读；执行器拒绝这种参数启动新转换。
    cleaning_preview_job_id: int | None = Field(default=None, strict=True, gt=0)


def tool_parameters(
    manifest: ToolManifest, roots: tuple[StorageRootConfig, ...] | None = None
) -> type[ConversionParameters]:
    """为一个工具建立带型号、默认输出版本和空间百分比的参数模型。

    Args:
        manifest: 启动时已校验的工具清单。
        roots: 登记根快照；None 仅供独立工具参数读取，不提供提交选根能力。

    Returns:
        独立模型类；输出版本省略时取清单首项，空间百分比省略时取 runtime 默认值；
        提供 roots 时缺省输出根取首个可写根，显式不存在或只读根由 JobInputError 拒绝。

    Raises:
        无；调用返回模型时，非法型号或版本由Pydantic报告ValidationError。

    Side Effects:
        无；不读取工具程序或数据库。

    Time Semantics:
        模型约束是启动快照；执行前重新校验当前清单。
    """

    class _ToolParameters(ConversionParameters):
        """闭包保存单工具约束，不使用可变全局登记。"""

        input_format: ClassVar[str] = manifest.io.input_format
        output_roots: ClassVar[tuple[StorageRootConfig, ...] | None] = roots

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
            # fields_set 区分请求省略和显式给 25，不能拿数值是否等于旧默认来判断。
            ratio = (
                self.space_ratio_percent
                if "space_ratio_percent" in self.model_fields_set
                else manifest.runtime.space_ratio_percent
            )
            root = select_root(roots, self.output_root) if roots is not None else None
            return self.model_copy(
                update={
                    "output_format": version,
                    "space_ratio_percent": ratio,
                    "output_root": root.name if root is not None else self.output_root,
                }
            )

    return _ToolParameters


def selected_inputs(
    session: Session, parameters: InputSelection, *, input_format: str
) -> tuple[Path, ...]:
    """按用户顺序读取同一规范入口下符合工具输入格式的数据块位置。

    Args:
        session: 调用方管理的短数据库事务。
        parameters: 已通过结构校验的转换或清洗输入选择，数据块至多200项。
        input_format: 已校验清单声明的非空格式名，如 mcap 或 agibot_native。

    Returns:
        与source_ids逐项对应的绝对路径元组；仅为索引值，不表示文件在线。

    Raises:
        JobInputError: 数据集无唯一规范入口，数据块不属于它、重复登记或格式与 input_format 不符。
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
        or any(row.format != input_format for row in rows)
    ):
        raise JobInputError(
            invalid_field(
                "source_ids", f"全部属于该数据集且格式为{input_format}的数据块"
            ).diagnostics
        )
    paths = tuple(Path(by_id[identifier].direct_path) for identifier in parameters.source_ids)
    if input_format == "archives":
        validate_paths(paths)
    return paths


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
