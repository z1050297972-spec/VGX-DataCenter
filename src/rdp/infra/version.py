"""基础层的部署布局与版本事实（11 M1/M2），不调用 git、不读取当前工作目录。

包版本复用 importlib.metadata，构建信息复用标准库 json；只支持安装脚本的源码 worktree 布局。
不自行实现版本发现框架，不把开发仓库 HEAD 当作正在运行的部署版本。
"""

from collections.abc import Callable
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter, ValidationError

from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    InputError,
)


@dataclass(frozen=True)
class DeploymentLayout:
    """安装脚本和运行入口共享的部署位置。

    Attributes:
        root: 部署 worktree 的绝对根目录；不要求等于当前目录。
        web_dist: root/src/web/dist 的绝对路径，启动 Web 时校验 index.html。
        build_info: root/rdp-build.json 的绝对路径，由部署脚本原子写入。
    """

    root: Path
    web_dist: Path
    build_info: Path


def deployment_layout(package_file: Path) -> DeploymentLayout:
    """从已加载 rdp 包的位置确定源码部署布局。

    Args:
        package_file: rdp/__init__.py 的绝对路径，必须位于 <部署目录>/src/rdp；不接受 wheel 布局。

    Returns:
        三个绝对路径；不检查 dist 或构建信息存在性，不查找其他仓库。

    Raises:
        InputError: 路径不是绝对路径或不符合源码部署布局，提示使用安装脚本。
        ExternalError: 解析包路径遇到权限或文件系统故障。

    Side Effects:
        无（只解析包文件位置，不调用 git 或读取 home）。

    Time Semantics:
        每次入口启动确定一次布局；运行期间不随 cwd 改动。
    """
    if not package_file.is_absolute() or package_file.parts[-3:] != ("src", "rdp", "__init__.py"):
        raise InputError((_diagnostic("package_file", "使用安装脚本的 src/rdp 源码部署布局"),))
    try:
        package_file = package_file.resolve()
    except OSError as error:
        raise ExternalError(
            (_diagnostic("package_file", "可解析的包路径", DiagnosticCategory.EXTERNAL),)
        ) from error
    if package_file.parts[-3:] != ("src", "rdp", "__init__.py"):
        raise InputError((_diagnostic("package_file", "使用安装脚本的 src/rdp 源码部署布局"),))
    root = package_file.parents[2]
    return DeploymentLayout(root, root / "src/web/dist", root / "rdp-build.json")


def read_platform_version(
    layout: DeploymentLayout, *, package_version: Callable[[str], str]
) -> str:
    """读取包元数据与构建提交，生成命令、网页和作业共用的版本文字。

    Args:
        layout: 可信部署布局；只读其中的 build_info。
        package_version: importlib.metadata.version 或替身，接收包名 rdp；不在导入期调用。

    Returns:
        格式为 <包版本> (<提交前七位>)；构建文件缺失时提交显示“未知”。
        文件为 UTF-8 JSON 对象，仅含 commit，值为 40 或 64 位小写十六进制完整提交号。
        包元数据缺失时包版本也显示“未知”；最终文字 1-128 个码点、不含控制字符。

    Raises:
        InputError: 文件超出 4096 字节、JSON/commit 格式错误，或元数据版本含控制字符/导致总长超限。
        ExternalError: 文件存在但无法读取；不把权限问题伪装成缺失。
        DefectError: 元数据提供器发生 PackageNotFoundError 以外的异常或返回非字符串。

    Side Effects:
        无（有界读取构建文件和包元数据，不运行外部命令、不写回文件）。

    Time Semantics:
        每个服务启动读取一次并保存快照；作业领取使用该进程快照，运行中不重新读取部署文件。
    """
    try:
        with layout.build_info.open("rb") as stream:
            content = stream.read(_BUILD_INFO_MAX_BYTES + 1)
        if len(content) > _BUILD_INFO_MAX_BYTES:
            raise InputError((_diagnostic("build_info", "最多 4096 字节的 UTF-8 JSON"),))
        try:
            commit = _BuildInfo.model_validate_json(content.decode("utf-8")).commit[:7]
        except (ValidationError, UnicodeError) as error:
            raise InputError(
                (_diagnostic("build_info", "仅含 40 或 64 位小写十六进制 commit 的 JSON 对象"),)
            ) from error
    except FileNotFoundError:
        commit = "未知"
    except OSError as error:
        raise ExternalError(
            (_diagnostic("build_info", "可读取的构建文件", DiagnosticCategory.EXTERNAL),)
        ) from error
    try:
        version = package_version("rdp")
    except PackageNotFoundError:
        version = "未知"
    except Exception as error:
        raise DefectError from error
    if not isinstance(cast(object, version), str):
        raise DefectError
    result = f"{version} ({commit})"
    try:
        PLATFORM_VERSION_TEXT.validate_python(result)
    except ValidationError as error:
        raise InputError((_diagnostic("version", "1-128 个码点且无控制字符"),)) from error
    return result


def _diagnostic(
    field: str, expected: str, category: DiagnosticCategory = DiagnosticCategory.INPUT
) -> Diagnostic:
    """构建版本边界诊断，不回显构建文件或元数据中的不可信内容。"""
    return Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=category,
        stage="读取部署版本",
        source="平台",
        objects=(DiagnosticObject(key="field", value=field),),
        rule="部署信息必须符合版本契约",
        actual="路径、内容或访问条件不符合要求",
        expected=expected,
        consequence="拒绝启动或显示不可信版本",
        next_step="检查部署文件与权限，使用安装脚本重新构建",
    )


# 构建信息仅含提交号；4096 字节为公开读取上限，多读一个字节用于判断超限。
_BUILD_INFO_MAX_BYTES = 4096


class _BuildInfo(BaseModel):
    """严格校验部署文件，不接受额外字段或隐式类型转换。"""

    model_config = ConfigDict(extra="forbid", strict=True)
    commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


# CLI、API 与领取事务共用同一文字规则，防止各边界接受不同的执行版本。
PLATFORM_VERSION_TEXT = TypeAdapter(
    Annotated[
        str,
        StringConstraints(
            strict=True,
            min_length=1,
            max_length=128,
            pattern=r"^[^\x00-\x1f\x7f-\x9f\u2028\u2029]+$",
        ),
    ]
)
