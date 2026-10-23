"""健康接口的响应契约（入口层），只表示 Web 可响应，不探测数据库或 worker。

使用已批准的 pydantic 定义响应与 OpenAPI，避免前后端分别维护接口类型。
依据：M0 工单 02、ADR 0001；worker 在线状态在后续作业工单处理。
"""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """健康接口的固定响应结构。

    Attributes:
        status: Web 可响应的状态，无单位，仅允许字符串 ok；不是 worker 的在线状态。
    """

    status: Literal["ok"]


def get_health() -> HealthResponse:
    """返回 Web 入口可响应的健康状态。

    Args:
        无

    Returns:
        status 为 ok 的 HealthResponse，序列化为 {"status": "ok"}。

    Raises:
        无

    Side Effects:
        无；不访问数据库、导航层、存储根或网络。

    Time Semantics:
        同步返回当次请求的状态，不读取时钟、不等待或重试。
    """
    return HealthResponse(status="ok")
