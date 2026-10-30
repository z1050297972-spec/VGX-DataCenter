"""数据来源标注的提交参数（领域层，M1-10）；只校验输入，不读导航层或执行作业。"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from rdp.jobs.dataset_browser.schemas import DatasetId
from rdp.jobs.navwrite.policy import DATA_ORIGINS

DATA_ORIGIN_PREVIEW_TYPE = "nav_data_origin_preview"


class DataOriginParameters(BaseModel):
    """一次数据来源标注预览的输入。

    Attributes:
        model_config: 冻结，拒绝多余字段，不回显不可信输入。
        dataset_id: 永久编号，1 至 256 码点，不含路径分隔符、空白或 NUL。
        data_origin: DATA_ORIGINS 中的中文来源值，不接受操作者或路径。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    dataset_id: DatasetId
    data_origin: str = Field(json_schema_extra={"enum": list(DATA_ORIGINS)})

    @field_validator("data_origin")
    @classmethod
    def _known_origin(cls, value: str) -> str:
        """来源取值复用第 07 张，不能另造同义名称。"""
        if value not in DATA_ORIGINS:
            raise ValueError("数据来源不在取值表里")
        return value
