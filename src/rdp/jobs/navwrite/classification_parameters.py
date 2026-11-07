"""分类值删除的参数边界（领域层，M1.5-16）；复用 Pydantic，不接收路径或写入计划。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rdp.jobs.datasets.vocabulary import UNLABELED

CLASSIFICATION_REMOVE_PREVIEW_TYPE = "nav_classification_remove_preview"


class ClassificationRemoveParameters(BaseModel):
    """删除所有规范副本中指定的一个分类值。

    Attributes:
        model_config: 冻结且拒绝额外字段，错误不回显原输入。
        kind: scene 或 tasks，只允许这两个顶层字段。
        value: 非空分类文本；使用现有候选原值，不接受未标注占位符。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    kind: Literal["scene", "tasks"]
    value: str = Field(strict=True, min_length=1)

    @field_validator("value")
    @classmethod
    def _deletable_value(cls, value: str) -> str:
        """未标注是筛选占位符，不能成为删除目标；候选原值不做隐式修剪。"""
        if not value.strip() or value.strip() == UNLABELED:
            raise ValueError("不能删除未标注或空白值")
        return value
