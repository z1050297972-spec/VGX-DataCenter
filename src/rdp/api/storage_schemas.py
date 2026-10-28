"""存储根只读响应（入口层，10）；只公开状态摘要，不公开 UUID、NFS 来源或挂载表原文。"""

from datetime import timedelta
from typing import Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from rdp.infra.storage import OFFLINE_REASON_LABELS, OfflineReason


class StorageRootResponse(BaseModel):
    """页面上的单根状态，时间由服务器提供。

    Attributes:
        name: 配置里的稳定名字。
        path: 登记绝对路径的文本，不表示 Web 已访问目录。
        writable: 平台许可，True 显示可写，False 显示只读。
        online: 此次挂载身份核对是否通过。
        reason: 在线为 None，离线为三种 OfflineReason 之一；本 GET 不产生 timeout。
        checked_at: aware UTC 检查结束时刻，浏览器仅在展示时转本地时间。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    name: str
    path: str
    writable: bool
    online: bool
    reason: OfflineReason | None = Field(
        json_schema_extra={
            "x-display-labels": {
                reason.value: label for reason, label in OFFLINE_REASON_LABELS.items()
            }
        }
    )
    checked_at: AwareDatetime

    @model_validator(mode="after")
    def validate_status(self) -> Self:
        """拒绝在线标志与离线原因自相矛盾的服务端响应。

        Args:
            无。

        Returns:
            当前响应，online 与 reason 互相一致，checked_at 偏移为零。

        Raises:
            ValueError: 在线有原因、离线无原因或时刻不是 UTC；由响应边界归程序缺陷。

        Side Effects:
            无；只核对内存响应，不访问 path。

        Time Semantics:
            不重新取时钟，保留基础层检查时刻。
        """
        if self.online != (self.reason is None):
            raise ValueError("在线标志与离线原因不一致")
        if self.checked_at.utcoffset() != timedelta(0):
            raise ValueError("检查时刻须为UTC")
        return self


class StorageRootsResponse(BaseModel):
    """按配置顺序返回全部存储根，不分页、不缓存。

    Attributes:
        items: 每个登记根一条，配置为空时为空元组；不包含表外挂载点。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    items: tuple[StorageRootResponse, ...]
