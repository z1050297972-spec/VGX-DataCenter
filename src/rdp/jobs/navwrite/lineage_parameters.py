"""人工血缘的提交参数；复用 Pydantic 与数据集编号契约，不接收路径或操作人。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rdp.jobs.dataset_browser.schemas import DatasetId

# M3-05 的人工登记预算：每条 1 至 8 个输入，说明最多 500 个 Unicode 字符。
MAX_LINEAGE_INPUTS = 8
MAX_LINEAGE_NOTE_CHARS = 500
LINEAGE_PREVIEW_TYPE = "nav_lineage_preview"


class LineageParameters(BaseModel):
    """登记或删除一整条人工血缘记录。

    Attributes:
        dataset_id: 产物数据集永久编号。
        action: add 追加，remove 按记录编号删除。
        input_dataset_ids: add 必须提供 1 至 8 个不重复且不含自身的编号。
        note: add 的说明，0 至 500 字符；空字符串写成 null。
        record_id: remove 必填的正整数编号；不允许布尔值。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    dataset_id: DatasetId
    action: Literal["add", "remove"]
    input_dataset_ids: tuple[DatasetId, ...] = Field(default=(), max_length=MAX_LINEAGE_INPUTS)
    note: str | None = Field(default=None, strict=True, max_length=MAX_LINEAGE_NOTE_CHARS)
    record_id: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def _action_fields(self) -> Self:
        """两个动作不能夹带另一动作的字段，避免用户以为被忽略的值已生效。"""
        if self.action == "add":
            if not self.input_dataset_ids or self.record_id is not None:
                raise ValueError("登记必须提供输入，不能提供记录编号")
            if self.dataset_id in self.input_dataset_ids or len(set(self.input_dataset_ids)) != len(
                self.input_dataset_ids
            ):
                raise ValueError("输入不能重复或包含自己")
        elif self.record_id is None or self.input_dataset_ids or self.note is not None:
            raise ValueError("删除只接收记录编号")
        return self
