"""回填预览的共享参数（领域层，M1.5-15）；Web 可导入，不带 worker 写入能力。"""

from typing import Final

from pydantic import BaseModel, ConfigDict

# 本次迁移固定覆盖全部导航数据集，不接受客户端指定路径或部分范围。
BACKFILL_PREVIEW_TYPE: Final = "nav_information_backfill_preview"


class BackfillParameters(BaseModel):
    """全量回填无业务参数，拒绝客户端传入计划、路径或身份。

    Attributes:
        model_config: 冻结、禁止额外字段且不回显输入。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
