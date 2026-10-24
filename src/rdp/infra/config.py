"""基础层的平台配置契约，只读 TOML，不创建状态目录、不配置日志。

依据 M0 工单 03 的 C1-C3、spec S1/S3；不依赖 state、logging 或入口层。
解析用标准库 tomllib，字段校验用已批准的 pydantic；只补配置来源和路径展开规则。
四类异常及诊断对象属于第 04 张，本票暂用内建 ValueError/OSError，不建平行异常体系。
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

# 09 号决策票限定四级；配置、运行日志设置共用此类型，避免两份枚举漂移。
type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]
# 工单 03 未定上限；本契约取十年，避免拼错数字造成无限制保留，待骨架评审确认。
MAX_RETENTION_DAYS = 3650


class WebConfig(BaseModel):
    """不可变的 Web 监听配置，不探测端口占用、不解析 DNS。

    Attributes:
        host: 监听地址或主机名，无单位；1 至 253 字符，不含空白、斜杠、反斜杠或 NUL；
            默认 0.0.0.0。只做字符串校验，可绑定性由第 11 张启动入口检查。
        port: TCP 端口，无单位；严格整数 1 至 65535，拒绝 bool 和字符串；默认 8600（S3）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)
    # 工单 03 明确要求默认监听全部接口，局域网部署边界由启动/认证工单负责。
    host: str = Field(
        default="0.0.0.0",  # noqa: S104  # 理由：工单 03 已批准的监听地址默认值。
        min_length=1,
        max_length=253,
        pattern=r"^[^\s/\\\x00]+$",
    )
    port: int = Field(default=8600, ge=1, le=65535)


class LogConfig(BaseModel):
    """不可变的运行日志配置，仅配置文件可改变，网页不可修改（C3）。

    Attributes:
        level: 日志阈值，无单位；DEBUG、INFO、WARNING、ERROR 之一，区分大小写；默认 INFO。
        retention_days: 归档保留期，单位为当地日历天；严格整数 1 至 3650，拒绝 bool；默认 30。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)
    level: LogLevel = "INFO"
    retention_days: int = Field(default=30, ge=1, le=MAX_RETENTION_DAYS)


class PlatformConfig(BaseModel):
    """不可变的最终生效配置；嵌套模型也不可变，未知字段全部拒绝。

    Attributes:
        state_dir: 平台状态目录，无单位；绝对 Path，不含 NUL 或 .. 分量；构造时必填。
            load_config 的缺省值是注入 home 下的 .local/share/rdp。
            文件中允许绝对路径或 ~/ 前缀（也允许单独 ~），后者用注入 home 展开；
            不接受相对路径、~其他用户或环境变量展开，不解析软链接、不要求已存在。
        web: WebConfig，无单位；默认 WebConfig()，只允许 host/port。
        log: LogConfig，无单位；默认 LogConfig()，只允许 level/retention_days。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True, hide_input_in_errors=True)
    state_dir: Path
    web: WebConfig = Field(default_factory=WebConfig)
    log: LogConfig = Field(default_factory=LogConfig)

    @field_validator("state_dir")
    @classmethod
    def validate_state_dir(cls, value: Path) -> Path:
        """校验已经展开的状态目录，不访问文件系统。

        Args:
            value: 无单位的绝对 Path；不含 NUL 或 .. 分量。

        Returns:
            原 Path 值，不解析软链接、不创建目录。

        Raises:
            ValueError: value 是相对路径或含 NUL、..；经模型调用时由 pydantic
                包装为 ValidationError，load_config 再转换成带来源的 ValueError。

        Side Effects:
            无。

        Time Semantics:
            无时钟读取或等待。
        """
        raise NotImplementedError


@dataclass(frozen=True)
class LoadedConfig:
    """配置读取结果及启动日志所需的来源，不增加配置文件字段。

    Attributes:
        config: 最终生效的 PlatformConfig，无单位；必填，无默认值。
        source: 实际尝试读取的配置文件绝对 Path，无单位；必填，无默认值。
        used_defaults: 是否因为缺省路径不存在而全部使用默认配置；布尔值，必填，无默认值。
            空文件或只写部分配置时为 False，即使所有生效值恰好等于默认值。
    """

    config: PlatformConfig
    source: Path
    used_defaults: bool


def load_config(*, environ: Mapping[str, str], home: Path) -> LoadedConfig:
    """读取唯一配置文件并校验最终生效值，保留来源供启动边界报告。

    Args:
        environ: 环境变量快照，无单位；只读取 RDP_CONFIG，其他变量完全忽略（C2）。
            未设置或空字符串表示缺省路径；非空值须为绝对路径或 ~、~/ 前缀路径。
        home: 注入的用户目录，绝对 Path，不含 NUL 或 ..；不读取真实 home 或进程环境。

    Returns:
        LoadedConfig：RDP_CONFIG 有值时读指定文件；否则读 home/.config/rdp/config.toml。
        仅后者不存在时 used_defaults=True，所有项取默认值（C1）；
        文件存在时用 tomllib 读取 UTF-8 TOML，缺项补默认值，再由 pydantic 严格校验。
        state_dir 字符串先按上述规则展开成 Path；空表、空文件也合法。
        不转换字符串端口、不把 bool 当整数、不忽略任意层级的未知项。

    Raises:
        ValueError: home、RDP_CONFIG 或 state_dir 的路径形式非法，TOML/UTF-8 损坏，
            或任一配置项类型、范围、未知项校验失败。配置错误逐项包含文件绝对路径、
            点分项名、实际值和期望；拒绝启动并提示修正配置。解析错误项名为 <document>，
            实际值只含行列或编码错误位置，不回显整份文档。非法 home 的来源为 <arguments>。
            捕获 pydantic.ValidationError，按 errors(include_input=False) 的 loc/type
            构建逐项中文消息，再 raise ValueError(...) from error；不直接 str(error)。
            只回显本票五个已知叶子字段的标量实际值；未知项或容器用 <已隐藏>，
            后续敏感字段不加入回显白名单，避免异常链显示口令（模型隐藏输入）。
        FileNotFoundError: 非空 RDP_CONFIG 指定的文件不存在；含文件名，绝不回退默认值。
        OSError: 文件是目录、无读取权限或其他读取失败；保留原异常及路径，不吞掉。

    Side Effects:
        无（只读指定文件）；不建目录、不修改 environ、不读其他配置文件、不打日志。
        第 11 张入口先读配置、建目录、配置日志，再调用 log_config_source，
        由该函数在 used_defaults=True 时记录一次“使用默认配置”；失败仅由入口报告。

    Time Semantics:
        同步读取本地文件，无重试；结果是本次读取快照，不监控修改，变更须重启。
    """
    raise NotImplementedError
