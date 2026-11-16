"""外部工具的离线环境参数（领域层，M4.6-02），不启动进程或创建缓存。

复用系统 env 的参数接口，不拼 shell；沙箱和等待上限仍由受管进程负责。
"""

from pathlib import Path


def offline_tool_argv(scratch: Path, argv: tuple[str, ...]) -> tuple[str, ...]:
    """为工具命令添加离线运行及私有 Hugging Face 缓存环境。

    Args:
        scratch: 本次执行的私有可写目录，绝对路径；HF_HOME 固定为其 hf-home 子目录。
        argv: 非空的程序及参数元组，首项为程序路径；各项原样传递，不经 shell。

    Returns:
        以 /usr/bin/env 和三项环境设置开头的命令元组，随后是完整 argv。

    Raises:
        无。

    Side Effects:
        无；不改当前进程环境，不创建目录或启动命令。

    Time Semantics:
        纯参数构造，不读取时钟；执行及超时由调用方的沙箱和受管进程控制。
    """
    return (
        "/usr/bin/env",
        "HF_HUB_OFFLINE=1",
        "PYTHONDONTWRITEBYTECODE=1",
        f"HF_HOME={scratch / 'hf-home'}",
        *argv,
    )
