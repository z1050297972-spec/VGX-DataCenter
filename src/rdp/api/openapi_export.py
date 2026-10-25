"""OpenAPI 离线导出入口，只写指定契约文件，不启动 Web 或读取平台数据。

使用 FastAPI 的 openapi、标准库 JSON 和 argparse；不重复维护接口 schema。
依据：ADR 0001、M0 工单 02；生成命令与过期检查共用本入口。
"""

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from rdp.api import create_app


class _Arguments(argparse.Namespace):
    """为 argparse 的公开解析边界提供确定类型，不传播动态属性。"""

    output_path: str | None = None
    help: bool = False


def export_openapi(output_path: Path) -> None:
    """将仅含接口的应用 OpenAPI 写成确定的 UTF-8 JSON 文件。

    Args:
        output_path: 输出文件路径，无单位；相对路径按调用时工作目录解释。
            父目录必须存在；允许覆盖现有普通文件，不自动创建父目录。

    Returns:
        无

    Raises:
        OSError: 输出父目录不存在、目标是目录、无写权限，或创建、写入、替换、清理临时文件失败。
        TypeError: create_app(None, database=None).openapi() 含无法序列化为 JSON 的值。
        ValueError: OpenAPI 含非有限数，无法输出标准 JSON。

    Side Effects:
        先完整序列化 create_app(None, database=None).openapi()，再写同目录临时文件；键排序，缩进为 2 个空格，
        ensure_ascii=False、allow_nan=False，末尾一个换行，编码 UTF-8。
        临时文件关闭成功后用 os.replace 原子替换目标；序列化、写入或替换失败时目标保持原样，
        并删除临时文件。若文件系统连清理也拒绝，抛出该 OSError，不把清理失败伪装成成功。
        不创建服务器或 socket，不访问导航层和存储根；成功后只保留指定输出文件。

    Time Semantics:
        同步导出，不读时钟、不写生成时刻；相同应用定义重复导出逐字节一致。
    """
    content = json.dumps(
        create_app(None, database=None).openapi(),
        sort_keys=True,
        indent=2,
        ensure_ascii=False,
        allow_nan=False,
    )
    temporary_path: Path | None = None
    try:
        # 必须同目录，确保原子替换不跨文件系统；关闭时的 flush 错误也不能破坏原文件。
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=output_path.parent, delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content + "\n")
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> Literal[0, 1, 2]:
    """解析 OpenAPI 导出参数并返回命令行退出码。

    Args:
        argv: 不含程序名的参数序列，无单位；None 表示 sys.argv[1:]。
            必须恰有一个输出路径，支持 -h/--help；未知选项或多余参数报错。

    Returns:
        0 表示导出成功或显示帮助；1 表示导出失败；2 表示参数错误。
        成功不输出文本；帮助写 stdout，参数或导出错误写 stderr，含原因及相关路径。

    Raises:
        OSError: stdout 或 stderr 写入失败，无法交付帮助或诊断。

    Side Effects:
        调用 export_openapi 写指定文件；失败产物语义同 export_openapi。
        参数错误和请求帮助不写文件；不启动服务，不监听端口。

    Time Semantics:
        同步运行，导出完成后退出，无轮询或重试。
    """
    # argparse 默认吞掉输出流的 OSError；只使用它解析和生成文本，由入口显式写流。
    parser = argparse.ArgumentParser(
        description="离线导出平台 OpenAPI",
        allow_abbrev=False,
        add_help=False,
        exit_on_error=False,
    )
    parser.add_argument("-h", "--help", action="store_true", help="显示帮助")
    parser.add_argument("output_path", nargs="?", help="输出 JSON 文件路径")
    arguments = _Arguments()
    try:
        _, unknown = parser.parse_known_args(argv, namespace=arguments)
    except argparse.ArgumentError as error:
        sys.stderr.write(f"error: 参数错误: {error}\n")
        return 2
    if unknown:
        sys.stderr.write(
            parser.format_usage() + f"error: 必须恰有一个输出路径；未知参数: {unknown}\n"
        )
        return 2
    if arguments.help:
        sys.stdout.write(parser.format_help())
        return 0
    if arguments.output_path is None:
        sys.stderr.write(parser.format_usage() + "error: 缺少输出路径\n")
        return 2
    try:
        export_openapi(Path(arguments.output_path))
    except (OSError, TypeError, ValueError) as error:
        sys.stderr.write(f"导出失败: {arguments.output_path}: {error}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
