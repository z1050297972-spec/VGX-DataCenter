"""导航采集信息的纯值契约；读取与编辑共用 Pydantic 校验，不读取数据库或文件。

编号只表示永久身份，名称与启停状态由调用方在当前数据库事务解析。
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from rdp.infra.ids import MAX_SQLITE_INTEGER

# M3-03 规定每个数据集最多关联 16 台机器人；编号沿用 SQLite 永久编号范围。
MAX_COLLECTION_ROBOTS = 16
type CollectionStatus = Literal["planned", "collecting", "done"]
type CollectionIdentifier = Annotated[int, Field(strict=True, ge=1, le=MAX_SQLITE_INTEGER)]


class CollectionInformation(BaseModel):
    """导航层只保存采集状态与编号，不把可变名称复制成另一份事实。

    Attributes:
        status: planned、collecting 或 done，必填。
        method_id: 采集方式永久正整数编号，None 表示未填。
        purpose_id: 用途永久正整数编号，None 表示未填。
        robot_ids: 0 至 16 个机器人编号，去重保序。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    status: CollectionStatus
    method_id: CollectionIdentifier | None
    purpose_id: CollectionIdentifier | None
    robot_ids: tuple[CollectionIdentifier, ...] = Field(max_length=MAX_COLLECTION_ROBOTS)

    @field_validator("robot_ids", mode="after")
    @classmethod
    def _unique_robots(cls, value: tuple[int, ...]) -> tuple[int, ...]:
        """先限制输入规模再去重，防止重复编号绕过数组预算。"""
        return tuple(dict.fromkeys(value))


def read_collection(value: object) -> CollectionInformation | None:
    """将导航原值投影为有效采集信息，坏值局部降级。

    Args:
        value: collection 原始 JSON 值；缺键由调用方传 None。

    Returns:
        有效冻结值；null、缺键及形状非法返回 None，调用方可用原值区分缺失与非法。

    Raises:
        无。

    Side Effects:
        无；不修改原 JSON 或查询编号存在性。

    Time Semantics:
        纯解析，只代表传入快照，不读取时钟。
    """
    if value is None:
        return None
    try:
        return CollectionInformation.model_validate(value)
    except ValidationError:
        return None
