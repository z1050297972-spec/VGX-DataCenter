"""清洗作业参数（领域层，M4.5-02）；共用转换输入规则，不包含输出与空间选项。"""

import re
from typing import Self

from pydantic import model_validator

from rdp.jobs.conversion.parameters import InputSelection
from rdp.tools.manifest import ToolManifest


class CleaningPreviewParameters(InputSelection):
    """清洗选择，型号还须通过工具专属模型的 cleaning 登记校验。"""


def cleaning_preview_type_name(tool_name: str) -> str:
    """把工具登记名映射为永久清洗预览类型键。

    Args:
        tool_name: 清单中的 ASCII 小写字母、数字和可选连字符名称。

    Returns:
        cleaning_preview_ 前缀加去除非字母数字后的工具名。

    Raises:
        无；最终类型是否合法由登记表检查。

    Side Effects:
        无。

    Time Semantics:
        纯字符串转换，不读时钟。
    """
    return "cleaning_preview_" + re.sub("[^a-z0-9]", "", tool_name)


def tool_parameters(manifest: ToolManifest) -> type[CleaningPreviewParameters]:
    """生成只接受当前工具已登记清洗型号的参数模型。

    Args:
        manifest: 已校验且包含 cleaning 映射的工具清单。

    Returns:
        独立的参数类，保留输入顺序，拒绝未登记清洗规则的型号。

    Raises:
        无；使用返回类校验非法型号时由 Pydantic 抛出 ValidationError。

    Side Effects:
        无；闭包只引用清单快照。

    Time Semantics:
        启动约束在执行前重新加载核对，不能用排队时的清单代替执行时清单。
    """

    class _ToolParameters(CleaningPreviewParameters):
        """每个工具独立保存可选型号。"""

        @model_validator(mode="after")
        def _cleaning_model(self) -> Self:
            """转换支持某型号不等于它已经登记清洗规则。"""
            if self.robot_model not in manifest.cleaning:
                raise ValueError("型号没有登记清洗规则")
            return self

    return _ToolParameters
