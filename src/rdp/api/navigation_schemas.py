"""导航层恢复失败标记的 HTTP 字段（M1-07）；编号用十进制文本，不暴露 ORM 或文件正文。"""

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from rdp.jobs.navwrite.policy import MARKER_ITEM_SAMPLE_LIMIT


class NavigationPayload(BaseModel):
    """响应共同配置：冻结并拒绝未知字段。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class MismatchItemResponse(NavigationPayload):
    """一项对不上的步骤。

    Attributes:
        job_id: 所属写入作业编号，规范十进制文本。
        step_index: 在写入日志里的步骤序号，从 0 起。
        path: 相对导航层根的路径。
        expected_before: 前像的文字描述（哈希、链接目标或“不存在”）。
        expected_after: 后像的文字描述。
        actual: 磁盘现状的文字描述；读不了时写原因，不含文件正文。
    """

    job_id: str
    step_index: int = Field(ge=0)
    path: str = Field(min_length=1)
    expected_before: str = Field(min_length=1)
    expected_after: str = Field(min_length=1)
    actual: str = Field(min_length=1)


class RecoveryBlockResponse(NavigationPayload):
    """当前标记；没有标记时只有 blocked=false，其余字段省略。

    Attributes:
        blocked: 写导航层的作业是否被挡住。
        set_at: 第一次设置的 UTC 时刻；blocked=false 时省略。
        job_ids: 留有对不上项的写入作业编号（文本，升序）；blocked=false 时省略。
        items: 对不上的项样例，至多 MARKER_ITEM_SAMPLE_LIMIT 条；blocked=false 时省略。
        total_items: 对不上的项总数，≥ len(items)；blocked=false 时省略。
    """

    blocked: bool
    set_at: AwareDatetime | None = None
    job_ids: tuple[str, ...] | None = None
    items: tuple[MismatchItemResponse, ...] | None = Field(
        default=None, max_length=MARKER_ITEM_SAMPLE_LIMIT
    )
    total_items: int | None = Field(default=None, ge=1)


class AcknowledgeResponse(NavigationPayload):
    """管理员确认的结果。

    Attributes:
        cleared_job_ids: 已归档并清掉日志的作业编号（文本，升序）。
    """

    cleared_job_ids: tuple[str, ...]
