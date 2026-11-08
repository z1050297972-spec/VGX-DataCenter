"""外部工具的只读沙箱参数（领域层，M4-02）；只验证路径，不执行程序或修改存储。

复用 pathlib 的真实路径解析与 bwrap 的挂载隔离，不自己实现文件访问拦截。
"""

from dataclasses import dataclass
from pathlib import Path

from rdp.infra.diagnostics import (
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    InputError,
)


@dataclass(frozen=True)
class SandboxSpec:
    """工具运行中唯一允许持久写入的目录集合。

    Attributes:
        writable: 已存在的绝对目录，不能为根或覆盖只读存储；空元组表示无持久可写目录。
    """

    writable: tuple[Path, ...]


def sandbox_argv(
    argv: tuple[str, ...], spec: SandboxSpec, *, readonly_roots: tuple[Path, ...]
) -> tuple[str, ...]:
    """生成必须经 bwrap 执行的参数，拒绝可写目录越过只读边界。

    Args:
        argv: 非空工具参数元组，首项为绝对程序路径；由 ToolCommand 再校验，不经 shell。
        spec: 此次作业的可写暂存目录集合，目录须已存在且为绝对路径。
        readonly_roots: 调用方传入的全部已登记只读存储根绝对路径，可为空。

    Returns:
        bwrap 绝对程序路径、隔离参数、可写绑定和原始工具参数，保持参数边界。

    Raises:
        InputError: 可写目录无效、是根目录，或与只读根有包含关系；诊断指出目录。
        OSError: 目录真实路径无法读取。

    Side Effects:
        无（只读解析目录和符号链接）；不探测 bwrap，不创建目录，无不加沙箱的回退。

    Time Semantics:
        同步验证调用时的目录状态；调用方须在执行前保持暂存目录归属和路径稳定。
    """
    roots = tuple(root.resolve() for root in readonly_roots)
    result = [
        "/usr/bin/bwrap",
        "--ro-bind",
        "/",
        "/",
        "--dev-bind",
        "/dev",
        "/dev",
        "--proc",
        "/proc",
        "--tmpfs",
        "/tmp",  # noqa: S108  # 理由：这是bwrap新建的私有tmpfs挂载点，不是宿主临时文件路径。
    ]
    for path in spec.writable:
        resolved = path.resolve()
        # 解析链接后判定，且不能把只读根的父目录整体绑定为可写，免得绕过子目录保护。
        if (
            not path.is_absolute()
            or not resolved.is_dir()
            or resolved == Path("/")
            or any(resolved.is_relative_to(root) or root.is_relative_to(resolved) for root in roots)
        ):
            raise InputError(
                (
                    Diagnostic(
                        level=DiagnosticLevel.ERROR,
                        category=DiagnosticCategory.INPUT,
                        stage="沙箱预检",
                        source="平台",
                        objects=(DiagnosticObject(key="writable", value=str(path)),),
                        rule="沙箱可写目录不得覆盖只读存储",
                        actual="目录不存在、不是绝对目录、是根目录或与只读根重叠",
                        expected="已存在且与只读根隔离的绝对暂存目录",
                        consequence="不启动工具",
                        next_step="为作业选择独立的可写暂存目录",
                    ),
                )
            )
        result.extend(("--bind", str(resolved), str(resolved)))
    return (*result, "--unshare-net", "--die-with-parent", "--", *argv)
