"""采集登记 HTTP 响应；复用领域输入和既有 HistoricalActorResponse，不另定义历史身份。"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from rdp.api.audit_schemas import HistoricalActorResponse
from rdp.collection.types import MethodInput, PurposeInput, RegistryStatus, RobotInput


class RegistryHistory(BaseModel):
    """创建/修改身份和 UTC 时间；账号编号沿用历史身份的十进制文本格式。"""

    model_config = ConfigDict(extra="forbid")
    status: RegistryStatus
    reference_count: int
    created_by: HistoricalActorResponse
    created_at: datetime
    updated_by: HistoricalActorResponse
    updated_at: datetime


class RobotResponse(RobotInput, RegistryHistory):
    """机器人完整登记响应，robot_id 是工单约定的整数。"""

    robot_id: int


class MethodResponse(MethodInput, RegistryHistory):
    """采集方式响应，包含对应数据来源。"""

    id: int


class PurposeResponse(PurposeInput, RegistryHistory):
    """用途响应，不含 data_origin。"""

    id: int


class RobotsResponse(BaseModel):
    """机器人按编号升序排列，包含停用项。"""

    items: tuple[RobotResponse, ...]


class ModelOptionsResponse(BaseModel):
    """登记型号与数据集索引型号合并、去重、排序后的候选。"""

    items: tuple[str, ...]


class VocabularyResponse(BaseModel):
    """两个词表独立按编号升序排列，包含停用项。"""

    methods: tuple[MethodResponse, ...]
    purposes: tuple[PurposeResponse, ...]
