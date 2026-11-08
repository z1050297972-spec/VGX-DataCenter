"""工具清单模型（领域层，M4-01）；Pydantic 校验结构，pathlib 校验登记包边界。

仅校验登记包及配置文件存在性，不访问工具程序、存储根或执行命令。
命令占位符和命名规则是本平台登记契约，标准库没有对应业务模型。
"""

from pathlib import Path, PurePosixPath
from typing import Annotated, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)


def _relative_path(value: str) -> str:
    """拒绝绝对路径、父级分量和空路径；符号链接边界由登记读取时再核对。"""
    path = PurePosixPath(value)
    if not value or value == "." or path.is_absolute() or ".." in path.parts or "\x00" in value:
        raise ValueError("必须是不含 .. 或 NUL 的非空相对文件路径")
    return value


RelativePath = Annotated[str, AfterValidator(_relative_path)]


class _ManifestModel(BaseModel):
    """所有清单分节共用冻结和未知字段拒绝策略。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ToolIdentity(_ManifestModel):
    """工具身份及说明；源码信息不参与可用性判断。

    Attributes:
        name: 输入2输出[-变体]，ASCII 小写字母和数字，与登记包目录名一致。
        version: 程序版本文本，非空。
        summary: 中文用途说明，非空。
        directory: 相对工具库根目录，不含 ..，解析后不得越出工具库。
        source_commit: 登记时的源码提交号，仅作说明；省略表示未知。
        source_note: 登记时源码状态说明；省略表示无补充。
    """

    name: str = Field(pattern=r"^[a-z0-9]+2[a-z0-9]+(-[a-z0-9]+)?$")
    version: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    directory: RelativePath
    source_commit: str | None = None
    source_note: str | None = None


class ToolProgram(_ManifestModel):
    """程序定位与登记时的指纹；平台不负责构建。

    Attributes:
        path: 相对工具目录的程序文件路径，不含 ..。
        size: 登记时程序大小，字节，严格正整数。
        sha256: 登记时程序 SHA-256，64 位小写十六进制。
    """

    path: RelativePath
    size: int = Field(gt=0, strict=True)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ToolIO(_ManifestModel):
    """输入输出格式声明，不读取数据或推断格式。

    Attributes:
        input_format: 输入格式名，非空。
        output_format: 输出格式名，非空。
        output_versions: 非空、无重复的输出版本元组，首项是默认值。
    """

    input_format: str = Field(min_length=1)
    output_format: str = Field(min_length=1)
    output_versions: tuple[str, ...] = Field(min_length=1)

    @field_validator("output_versions")
    @classmethod
    def _unique_versions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """保持默认版本顺序，同时拒绝重复版本。"""
        if len(set(value)) != len(value):
            raise ValueError("输出版本不得重复")
        return value


class ToolRuntime(_ManifestModel):
    """运行要求声明，本票不检测 GPU 或启动外部程序。

    Attributes:
        needs_gpu: 是否必须分配 GPU，布尔值。
        progress: 已知进度解析器名，当前只支持 mcap2lerobot-pty。
        external_programs: 工具运行时依赖的系统程序名，按清单顺序，可为空。
    """

    needs_gpu: bool = Field(strict=True)
    progress: Literal["mcap2lerobot-pty"]
    external_programs: tuple[str, ...]


class ToolCommands(_ManifestModel):
    """不经过 shell 的参数模板，不包含程序路径本身。

    Attributes:
        verify: 预检参数元组，须含 config 和 inputs 占位符。
        convert: 转换参数元组，config、output、format、inputs 各出现一次，禁用 --force。
    """

    verify: tuple[str, ...]
    convert: tuple[str, ...]

    @model_validator(mode="after")
    def _templates(self) -> Self:
        """限制占位符出现次数并保证多输入展开为独立参数，不允许覆盖产物。"""
        required = ("{config}", "{output}", "{format}", "{inputs}")
        if any(sum(arg.count(key) for arg in self.convert) != 1 for key in required):
            raise ValueError("command.convert 必须含 config、output、format、inputs 各一次")
        if any(not any(key in arg for arg in self.verify) for key in ("{config}", "{inputs}")):
            raise ValueError("command.verify 必须含 config、inputs")
        if any(arg == "--force" or arg.startswith("--force=") for arg in self.convert):
            raise ValueError("command.convert 不允许 --force")
        for command in (self.verify, self.convert):
            if any("{inputs}" in arg and arg != "{inputs}" for arg in command):
                raise ValueError("{inputs} 必须单独作为一个参数")
        return self


class ToolManifest(_ManifestModel):
    """平台登记清单；上下文 package_dir 提供登记包身份及配置文件边界。

    Attributes:
        schema_version: 清单格式版本，固定为 1。
        tool: 工具身份及源码说明。
        program: 程序相对路径、字节数及完整 SHA-256。
        io: 输入输出格式和有序输出版本。
        models: robot_model 字符串到登记包内配置相对路径的映射。
        runtime: GPU、进度解析器与外部程序要求。
        command: 预检与转换命令模板。
    """

    schema_version: Literal[1]
    tool: ToolIdentity
    program: ToolProgram
    io: ToolIO
    models: dict[str, RelativePath]
    runtime: ToolRuntime
    command: ToolCommands

    @model_validator(mode="after")
    def _package(self, info: ValidationInfo) -> Self:
        """提供登记包上下文时核对目录名和每个配置的真实位置。"""
        if info.context is None:
            return self
        package = Path(info.context["package_dir"])
        if self.tool.name != package.name:
            raise ValueError("tool.name 必须等于登记包目录名")
        for relative in self.models.values():
            config = (package / relative).resolve()
            if not config.is_relative_to(package.resolve()) or not config.is_file():
                raise ValueError(f"型号配置必须存在于登记包内：{relative}")
        return self
