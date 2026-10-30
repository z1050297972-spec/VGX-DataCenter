"""建链与新增数据集的输入契约（领域层，M1-08、ADR 0009 L1-L6）。

只校验值，不访问文件系统；存在性、挂载身份和重名检查由 worker builder 完成。
复用 Pydantic、格式登记表及 DATA_ORIGINS，不另维护格式或来源词表。
"""

from typing import Annotated, Self

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from rdp.jobs.dataset_browser.schemas import DatasetId

# 类型键写进永久作业记录；预览不写导航层，实际写入统一使用 nav_write_apply。
LINK_PREVIEW_TYPE = "nav_create_link_preview"
DATASET_PREVIEW_TYPE = "nav_create_dataset_preview"

# 导航层手册第 3 节固定的 14 项名称；首次创建只写编号、名称，正文保持空串。
INFORMATION_FIELD_NAMES = (
    "数据集标识",
    "地址",
    "类型与组成",
    "数据大小",
    "采集机器人型号",
    "任务与场景",
    "数据格式",
    "FPS",
    "相机配置",
    "状态维度",
    "动作维度",
    "动作控制方式及单位",
    "轨迹／帧数",  # noqa: RUF001  # 理由：保留导航层手册和现有 JSON 第 13 项的全角斜杠原名。
    "信息来源与核验日期",
)


def validate_entry_name(value: str) -> str:
    """校验数据集名与链接名共用的单层目录分量规则。

    Args:
        value: 原样名称，至少一个码点；不得含 / 或 NUL、不得以 . 开头，
            不得等于 REQUIRED_DOCUMENTS 或 PROVENANCE_DOCUMENT 中的文件名。不修剪或改写名称。

    Returns:
        校验通过的原字符串；数据集重名和链接目的冲突由 builder 另查。

    Raises:
        ValueError: 名称不满足上述规则，由 Pydantic 转为参数校验诊断。

    Side Effects:
        无。

    Time Semantics:
        同步纯校验，不读时钟或文件系统。
    """
    raise NotImplementedError


def validate_registered_format(value: str) -> str:
    """确认格式稳定键来自现有格式目录登记表。

    Args:
        value: 非空格式键，精确匹配 FORMAT_DIRECTORIES 的 format；不是磁盘目录名。

    Returns:
        原样格式键；archives 对应的实际目录名仍由登记表推导。

    Raises:
        ValueError: 值未登记，不自动猜测格式或新增目录规则。

    Side Effects:
        无。

    Time Semantics:
        仅查内存中的登记规则，无缓存过期或等待。
    """
    raise NotImplementedError


def validate_data_origin(value: str) -> str:
    """校验新增数据集必填的数据来源。

    Args:
        value: DATA_ORIGINS 中的中文值；允许显式选择未知，不接受省略、空串或英文筛选键。

    Returns:
        原样数据来源，用于 new_provenance，不推测采集任务或血缘。

    Raises:
        ValueError: 来源不在 DATA_ORIGINS 中。

    Side Effects:
        无。

    Time Semantics:
        无；不为来源生成记录时刻。
    """
    raise NotImplementedError


EntryName = Annotated[str, Field(strict=True, min_length=1), AfterValidator(validate_entry_name)]
RegisteredFormat = Annotated[str, Field(strict=True), AfterValidator(validate_registered_format)]


class CreationValue(BaseModel):
    """冻结的创建输入；拒绝未知字段且不在错误中回显输入。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class FormatEntrySelection(CreationValue):
    """要加入第一条链接的按格式入口位置，不接受任意入口路径。

    Attributes:
        format: 登记表中的格式稳定键。
        version: 有版本层的格式必须填写安全的单层版本名；无版本层必须为 None。
            这是视图位置，与数据块从 meta/info.json 读出的版本分别展示。
    """

    format: RegisteredFormat
    version: EntryName | None = None

    @model_validator(mode="after")
    def validate_version(self) -> Self:
        """核对格式登记表要求的版本层与选择值一致。

        Args:
            无。

        Returns:
            当前选择对象，format/version 不被修改。

        Raises:
            ValueError: 有版本层而未提供 version，或无版本层却提供 version。

        Side Effects:
            无。

        Time Semantics:
            模型构造时同步校验，不读取版本目录。
        """
        raise NotImplementedError


class FirstLink(CreationValue):
    """一条建链参数，目标解释与元信息读取只在 worker 中发生。

    Attributes:
        name: 安全单层链接名，适用 L1 的四份 JSON 保留名规则。
        target_path: 文件或目录的非空绝对 POSIX 路径，无 NUL；不接受客户端指定存储根或 realpath 结果。
        fallback_format: 无 meta/info.json 时必选的登记格式；有该文件时以文件为准。
            文件损坏、不可读或字段不合约不能降级到此值；缺文件时 version 固定 None。
    """

    name: EntryName
    target_path: str = Field(strict=True, min_length=1, pattern=r"^/[^\x00]*$")
    fallback_format: RegisteredFormat | None = None


class LinkPreviewParameters(CreationValue):
    """给现有数据集建链的预览参数，规范入口由永久编号查找。

    Attributes:
        dataset_id: 已存在数据集的永久编号；不接受按格式入口路径冒充规范副本。
        link: 本次要追加的单条链接。
        format_entries: 勾选的零到多个格式/版本位置，不能重复；每个位置放入本条链接。
            未勾选的已有按格式入口仍由规范副本重生成，保留它们自己的 links[]（L8）。
    """

    dataset_id: DatasetId
    link: FirstLink
    format_entries: tuple[FormatEntrySelection, ...] = ()


class DatasetPreviewParameters(CreationValue):
    """新增数据集的预览参数；编号与入口路径只能由平台分配。

    Attributes:
        dataset_name: 安全单层数据集名；不能与按任务下任何已有对象重名，包括断链。
        data_origin: DATA_ORIGINS 中的必填中文值。
        link: 新数据集的第一条链接；至少有这一条，不创建空数据集。
        format_entries: 零到多个去重格式位置，按登记表推导目录；每个放入第一条链接。
    """

    dataset_name: EntryName
    data_origin: Annotated[str, Field(strict=True), AfterValidator(validate_data_origin)]
    link: FirstLink
    format_entries: tuple[FormatEntrySelection, ...] = ()
