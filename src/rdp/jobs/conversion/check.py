"""LeRobot 入库检查的 worker 边界（领域层，M4-04、ADR 0008）。

文件解析使用已有 pyarrow 和系统 ffprobe，子进程用标准库限时并回收进程组。
本模块只读产物，不写报告、不改名、不写导航；调用作业负责发布同一份结果。
"""

import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from rdp.jobs.conversion._process import run_bounded
from rdp.jobs.conversion.check_models import CheckReport
from rdp.jobs.navwrite.errors import nav_external_error


def check_output(output: Path, expected_version: str) -> CheckReport:
    """只读检查 LeRobot 结构、计数、视频与抽样内容，返回同一份四层结论。

    Args:
        output: worker 已定位的绝对暂存产物目录（out 或 cleaned）；目录内不允许软链接越界。
        expected_version: 转换参数里的 v3.0 或 v2.1，必须与 info.json 一致。

    Returns:
        四层检查结果；首个不通过之后的层为未检查。结构的未知顶层字段为警告；
        视频时长偏差大于数值舍入误差、但不超过一帧时为警告；其他检查没有警告。
        计数只读 data parquet 元数据；内容检查所有行的向量维度，首/中/末 episode 的有限值。

    Raises:
        ExternalError: 检查子进程无法启动、超过300秒、回收超过框架的2秒预算或异常退出。
        ValidationError: 子进程返回了违反内部结果契约的数据。

    Side Effects:
        只读暂存文件；在系统临时目录建视频引用索引，退出或超时均删除并回收进程组。

    Time Semantics:
        检查等待至多300秒，进程组回收另外至多2秒；视频时长以秒比较，容差为1/fps，舍入误差为1微秒。
        不对机器人时间戳做重采样或对齐；抽样按 episode_index 排序。
    """
    try:
        with TemporaryDirectory(prefix="rdp-ingest-check-") as scratch:
            stdout, stderr, returncode = run_bounded(
                (
                    sys.executable,
                    "-m",
                    "rdp.jobs.conversion._check_child",
                    str(output),
                    expected_version,
                    scratch,
                )
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        problem = nav_external_error(
            "CONVERSION_CHECK", "入库检查进程无法运行、检查超时或进程组回收超时"
        )
        raise problem from error
    if returncode != 0:
        problem = nav_external_error("CONVERSION_CHECK", stderr.decode(errors="replace")[-4096:])
        raise problem
    return CheckReport.model_validate_json(stdout)
