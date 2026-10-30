"""导航字段编辑的公开参数与分页模型（M1.5-02）；不提供任意文件或任意 JSON 写入能力。

复用 Pydantic 校验和标准库 JSON；字段路径只定位规范副本中的编辑项，实际白名单由编辑规则维护。
"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rdp.jobs.dataset_browser.schemas import DatasetId

FIELD_PREVIEW_TYPE = "nav_fields_preview"
# 作业参数已有 16 KiB 总预算；条数再设上界，防止一次编辑夹带整个大子任务文件。
MAX_FIELD_CHANGES = 64
FIELD_PAGE_LIMIT = 20

type EditableDocument = Literal["数据集信息.json", "子任务.json", "原始路径.json"]
type FieldPath = tuple[
    Annotated[str, Field(strict=True)] | Annotated[int, Field(strict=True, ge=0)], ...
]
type FieldValue = str | tuple[str, ...]


class FieldValueModel(BaseModel):
    """编辑值模型：冻结、拒绝未知字段，不把未校验输入回显到诊断。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class FieldEdit(FieldValueModel):
    """一项字段改动。

    Attributes:
        document: 三份基础 JSON 之一；来源使用现有专用流程。
        expected_sha256: 表单读取的原字节摘要，防止预览覆盖填表期间的改动。
        path: 字段路径，最多三层；不接受文件系统路径。
        value: 新文本或字符串数组；空值表示清空，不表示删除键。
    """

    document: EditableDocument
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    path: FieldPath = Field(min_length=1, max_length=3)
    value: FieldValue

    @model_validator(mode="after")
    def _editable_shape(self) -> Self:
        """参数入队前使用同一白名单拒绝越权字段和错误值类型。"""
        from rdp.jobs.navwrite._field_rules import check_shape

        check_shape(self)
        return self


class FieldEditParameters(FieldValueModel):
    """一个数据集的一批编辑，沿用通用预览和确认流水线。

    Attributes:
        dataset_id: 已分配的永久数据集编号。
        changes: 1 至 MAX_FIELD_CHANGES 项；只发送改动项，不发送完整文档。
    """

    dataset_id: DatasetId
    changes: tuple[FieldEdit, ...] = Field(min_length=1, max_length=MAX_FIELD_CHANGES)

    @model_validator(mode="after")
    def _unique_paths(self) -> Self:
        """同一文件字段不允许重复覆盖，避免预览顺序决定最终值。"""
        paths = [(item.document, item.path) for item in self.changes]
        if len(paths) != len(set(paths)):
            raise ValueError("字段不能重复")
        return self


class EditableField(FieldValueModel):
    """表单中的一项可编辑值。

    Attributes:
        path: 与提交参数一致的 JSON 定位路径。
        label: 中文标签，包含编号或任务身份。
        value: 当前文本或多选值；缺省结构化字段显示为空。
        multiple: 是否使用字符串多选输入。
    """

    path: FieldPath
    label: str
    value: FieldValue
    multiple: bool = False


class EditableFieldsPage(FieldValueModel):
    """规范副本编辑页；大数组只返回请求页。

    Attributes:
        dataset_id: 请求的永久编号。
        entry_path: 唯一按任务入口的导航相对路径。
        document: 本次读取的 JSON 文件名。
        sha256: 本页所依据的完整文件原字节摘要。
        offset: 条目起始位置，非负；信息文件只有一组。
        limit: 每页条目数，1 至 FIELD_PAGE_LIMIT。
        total: 完整条目数，信息文件为 1。
        fields: 当前页的可编辑项，按文件原顺序。
        original_robot_types: 原文件 robot_type 的索引参考值，去重排序；空表示未读到有效值。
    """

    dataset_id: str
    entry_path: str
    document: EditableDocument
    sha256: str
    offset: int
    limit: int
    total: int
    fields: tuple[EditableField, ...]
    original_robot_types: tuple[str, ...] = ()


class EditableFieldsQuery(FieldValueModel):
    """一页编辑项的读取条件。

    Attributes:
        document: 三份基础 JSON 之一。
        offset: 条目偏移，非负整数。
        limit: 每页 1 至 FIELD_PAGE_LIMIT 条。
    """

    document: EditableDocument
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=FIELD_PAGE_LIMIT, ge=1, le=FIELD_PAGE_LIMIT)
