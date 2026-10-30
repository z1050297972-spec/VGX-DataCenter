"""改指向的值契约（M1-09、L17）；只校验文本，不访问目标。"""

from pathlib import PurePosixPath

from pydantic import Field, field_validator

from rdp.jobs.dataset_browser.schemas import DatasetId
from rdp.jobs.navwrite.create_models import CreationValue

# 持久化作业类型键；真正写入仍使用 nav_write_apply。
REPOINT_PREVIEW_TYPE = "nav_repoint_preview"


class RepointParameters(CreationValue):
    """一次一个数据集的前缀替换输入。

    Attributes:
        dataset_id: 索引中的永久数据集编号。
        old_prefix: 不带结尾斜杠的绝对旧前缀，无 NUL 或父目录跳转。
        new_prefix: 同样约束的新前缀；worker 核对本地登记根及路径存在性。
    """

    dataset_id: DatasetId
    old_prefix: str = Field(strict=True, min_length=1)
    new_prefix: str = Field(strict=True, min_length=1)

    @field_validator("old_prefix", "new_prefix")
    @classmethod
    def _prefix(cls, value: str) -> str:
        """保留原样路径，拒绝会使前缀分量边界含糊的输入。"""
        if (
            not PurePosixPath(value).is_absolute()
            or value.endswith("/")
            or "\x00" in value
            or ".." in value.split("/")
        ):
            raise ValueError("前缀必须是不带结尾斜杠的绝对路径，不能包含父目录跳转")
        return value
