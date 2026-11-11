"""工具只读响应（入口层，M4-01）；清单无效时未知字段为 null，不合成虚假的版本。"""

from pydantic import BaseModel, ConfigDict

from rdp.infra.diagnostics import Diagnostic
from rdp.jobs.conversion.lerobot import LeRobotEnvironment
from rdp.tools.manifest import ToolCommands
from rdp.tools.registry import ToolConfiguration, ToolStatus


class ToolSummaryResponse(BaseModel):
    """工具列表中的一条状态。

    Attributes:
        name: 登记包目录名。
        version: 程序版本；清单无效时为 None。
        summary: 工具用途；清单无效时为 None。
        input_format: 输入格式；清单无效时为 None。
        output_format: 输出格式；清单无效时为 None。
        output_versions: 按清单顺序的输出版本；清单无效时为空。
        robot_models: 按清单顺序的适用型号字符串；清单无效时为空。
        cleaning_models: 按清单顺序的有清洗规则型号；清单无效时为空。
        needs_gpu: 是否必须分配 GPU；清单无效时为 None。
        status: 四种工具状态之一。
        diagnostics: 统一五段诊断，可用时为空。
        program_path: 已核对边界的程序绝对路径；清单无效时为 None。
        sha256_prefix: 登记的程序 SHA-256 前 12 位；清单无效时为 None。
        readme_available: 工具目录内是否存在普通 README.md；清单无效或路径越界时为 False。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    version: str | None
    summary: str | None
    input_format: str | None
    output_format: str | None
    output_versions: tuple[str, ...]
    robot_models: tuple[str, ...]
    cleaning_models: tuple[str, ...]
    needs_gpu: bool | None
    status: ToolStatus
    diagnostics: tuple[Diagnostic, ...]
    program_path: str | None
    sha256_prefix: str | None
    readme_available: bool


class ToolReadmeResponse(BaseModel):
    """工具本体目录的只读使用说明。

    Attributes:
        name: 登记包目录名，与工具列表中的名称一致。
        content: README 的完整 UTF-8 文本，原始字节不超过 1 MiB，保留换行。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    name: str
    content: str


class ToolListResponse(BaseModel):
    """当前工具登记列表。

    Attributes:
        items: 按工具名排序，空登记目录返回空元组，不过滤无效清单。
        lerobot_environment: 本次请求的解释器版本与指纹状态；探测失败保留错误说明。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")
    items: tuple[ToolSummaryResponse, ...]
    lerobot_environment: LeRobotEnvironment


class ToolDetailResponse(ToolSummaryResponse):
    """列表摘要之外的登记详情，不读取工具源码或工具目录的配置。

    Attributes:
        configurations: 每个型号的文件名、配置全文与完整 SHA-256；清单无效时为空。
        command: 两条命令模板；清单无效时为 None。
        source_commit: 登记时的提交说明；未填写或清单无效时为 None。
        source_note: 登记时源码状态说明；未填写或清单无效时为 None。
    """

    configurations: tuple[ToolConfiguration, ...]
    command: ToolCommands | None
    source_commit: str | None
    source_note: str | None
