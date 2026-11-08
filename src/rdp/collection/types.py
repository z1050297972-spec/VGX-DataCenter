"""采集登记领域输入；用已批准的 Pydantic 和标准库校验，不涉及 HTTP 或连接机器人。

标准库 ipaddress 校验 IP；MAC 和 RFC 1123 主机名没有标准库专用校验器，
使用 re 表达本票规定的固定格式，不引入网络探测或新依赖。
"""

import ipaddress
import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

# M3-01/02 的字符数和端口上限；名称先去首尾空白再计算字符数。
type Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
type ShortName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)
]
type CollectionOrigin = Literal["真机采集", "UMI 采集", "ego 采集", "仿真生成"]
type RegistryKind = Literal["robots", "methods", "purposes"]
type RegistryStatus = Literal["active", "retired"]
# collection 不能依赖上层 jobs；测试与 DATA_ORIGINS 对照，防止两个来源集合漂移。
COLLECTION_DATA_ORIGINS = frozenset({"真机采集", "UMI 采集", "ego 采集", "仿真生成"})


def _mac(value: str) -> str:
    """接受统一的连字符或冒号分隔，存储小写冒号形式。"""
    if re.fullmatch(r"[0-9a-fA-F]{2}([:-])(?:[0-9a-fA-F]{2}\1){4}[0-9a-fA-F]{2}", value) is None:
        raise ValueError("MAC 必须是六组十六进制数，以冒号或连字符分隔")
    return value.lower().replace("-", ":")


def _address(value: str) -> str:
    """IP 用标准库解析；主机名按 RFC 1123 的 ASCII 标签规则验证，不做 DNS 请求。"""
    try:
        ipaddress.ip_address(value)
    except ValueError:
        labels = value.removesuffix(".").split(".")
        if not all(
            re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
            for label in labels
        ):
            raise ValueError("地址必须是 IPv4、IPv6 或 RFC 1123 主机名") from None
    return value


class CollectionInput(BaseModel):
    """拒绝凭据和未知字段的不可变输入，领域函数与 HTTP 复用同一校验。"""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class RobotMac(CollectionInput):
    """单块网卡；接口名可空，MAC 保存规范形式。"""

    interface: ShortName | None = None
    mac: Annotated[str, AfterValidator(_mac)]


class RobotInput(CollectionInput):
    """完整机器人登记值；PUT 替换全部可编辑字段，不接受状态或操作者。"""

    name: Name
    robot_model: Name
    serial_number: Name | None = None
    macs: Annotated[tuple[RobotMac, ...], Field(max_length=8)] = ()
    address: (
        Annotated[str, StringConstraints(min_length=1, max_length=253), AfterValidator(_address)]
        | None
    ) = None
    ssh_port: Annotated[int, Field(strict=True, ge=1, le=65535)] = 22
    ssh_user: (
        Annotated[str, StringConstraints(min_length=1, max_length=32, pattern=r"^\S+$")] | None
    ) = None


class PurposeInput(CollectionInput):
    """用途名称，去首尾空白后 1 至 32 字符。"""

    name: ShortName


class MethodInput(PurposeInput):
    """采集方式必须明确选择平台自产数据的四种来源之一。"""

    data_origin: CollectionOrigin
