"""资源演示类型（领域层，09）；只执行注入的 nvidia-smi 或追加状态目录示例文件。

不访问导航层或数据盘；文件核对与写入分开，框架的共享 NavigationWriter 保证顺序。
使用标准库 JSON/有界尾读，不另造存储协议或依赖。
"""

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from rdp.jobs.execution import ExecutionContext
from rdp.jobs.policy import (
    GPU_EXAMPLE_MAX_HOLD_S,
    NAVIGATION_EXAMPLE_MAX_PAUSE_S,
    NAVIGATION_EXAMPLE_VALUE_MAX_CHARS,
)


class GpuExampleParameters(BaseModel):
    """示例占卡参数，不能指定物理卡号或命令路径。

    Attributes:
        hold_s: 严格整数秒数，0 至 GPU_EXAMPLE_MAX_HOLD_S=600；必填。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    hold_s: int = Field(strict=True, ge=0, le=GPU_EXAMPLE_MAX_HOLD_S)


class NavigationExampleParameters(BaseModel):
    """写锁演示的预览值和有界暂停。

    Attributes:
        expected_value: 预览看到的最后一条 value，0-256 码点；文件不存在时必须为空字符串。
        pause_s: 核对通过后、追加前的暂停，严格整数秒数 0-10，默认零；持锁期间不响应取消。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    expected_value: str = Field(strict=True, max_length=NAVIGATION_EXAMPLE_VALUE_MAX_CHARS)
    pause_s: int = Field(default=0, strict=True, ge=0, le=NAVIGATION_EXAMPLE_MAX_PAUSE_S)


@dataclass(frozen=True)
class NavigationExampleValue:
    """演示文件最后一条已完整写入的状态。

    Attributes:
        job_id: 最后写入作业的正编号，文件不存在时 None。
        value: 文件中的 value，缺文件为 ""；写入的新值固定为当前作业规范十进制编号文本。
    """

    job_id: int | None
    value: str


def read_example_value(path: Path) -> NavigationExampleValue:
    """有界读取示例文件的最后一行 JSON，不读真实导航层。

    Args:
        path: StatePaths.navigation_example 的绝对可信路径；只能位于本次状态根中。

    Returns:
        最后一个以换行结束的非空 JSON 对象的 job_id/value；文件不存在为 (None, "")。
        已存在的空文件也表示尚无值，不将损坏尾行当成文件不存在。

    Raises:
        InputError: 尾行未完整换行、超过 NAVIGATION_EXAMPLE_LINE_MAX_BYTES、JSON/字段/编号损坏。
        ExternalError: 文件权限、读取或关闭失败。
        DefectError: 非绝对路径、软链接、非普通文件或错误依赖。

    Side Effects:
        无（最多读取文件末尾 NAVIGATION_EXAMPLE_LINE_MAX_BYTES 字节）；不自动修复或截断坏行。

    Time Semantics:
        核对调用须已持框架导航锁；其他用途只代表读取瞬间，不保证其后状态不变。
    """
    raise NotImplementedError


def execute_gpu_example(context: ExecutionContext) -> None:
    """通过外部进程入口演示一张卡的隔离环境，再可取消地占用名额。

    Args:
        context: example_gpu 上下文，GpuExampleParameters，已通过存在性核对并持有卡号。

    Returns:
        无；外部工具零退出且占用期结束后上报一个完成条目；类型恢复方式为 interrupt。

    Raises:
        JobCancelledError: 工具执行或等待期间取消，交执行器归还 GPU。
        WorkerStoppingError: 入口停止，作业留待下一实例标记中断，仍归还已回收资源。
        ExternalError: nvidia-smi 失败/超时、没有可用配置卡或日志/进度持久化失败。
        InputError: 进度数据库损坏。
        ConflictError: 已进入进度事务后的竞争失败。
        DefectError: 参数/依赖/卡号不合法，不能自行挑卡或改用 CPU。

    Side Effects:
        context.run_process 运行注入的 gpu_example_command，使用 nvidia-smi -i <所领卡号>，输出进入作业日志；
        框架设置 CUDA_VISIBLE_DEVICES 和 CUDA_DEVICE_ORDER，并将实际传给此子进程的两项值写成一行作业日志；
        该行来自最终环境映射，不从配置另算展示值，类型不自行拼环境变量。
        采用 -i 明确展示卡号，nvidia-smi 列举硬件本身不作为 CUDA 可见设备数量的证明。
        然后用 reporter.wait 的有界片段等待，不做 GPU 计算、不分配显存，示例占用的是平台名额。

    Time Semantics:
        命令上限 GPU_PROBE_TIMEOUT_S，等待总量 hold_s<=600 用注入 monotonic；每段不超过 reporter.wait 上限。
    """
    raise NotImplementedError


def execute_navigation_example(context: ExecutionContext) -> None:
    """在共享写锁下核对示例状态，匹配后追加当前作业的新值。

    Args:
        context: example_navigation 上下文，NavigationExampleParameters；示例路径仅取必填的 navigation_example_path，不访问资源池或配置。

    Returns:
        无；成功追加 JSON 行 {job_id: 当前正编号, value: 当前编号文本} 后报告一个完成条目。

    Raises:
        ConflictError: 期待值不等于尾行 value，诊断含当前/最后写入 job_id、实际/期望、
            “在你预览之后被作业 #N 改过”及重新预览建议；不调用写入回调。
            等锁超时同样按框架冲突处理。
        JobCancelledError: 等锁时取消或写完放锁后的下一检查点取消，已经追加的行保留。
        WorkerStoppingError: 等锁时停止或写完后停止；恢复方式 interrupt。
        InputError: 示例文件尾部损坏或数据库损坏。
        ExternalError: 文件打开、追加、flush/fsync 或资源上报失败。
        DefectError: 参数、路径、时钟或执行依赖非法。

    Side Effects:
        context.write_navigation 接收分别定义的 verify/write；只在核对成功后暂停 pause_s 再追加一行。
        新文件使用属主读写权限；不覆盖旧行，flush/fsync 后才报告完成，失败可能留下可识别的不完整尾行，
        后续 read_example_value 拒绝继续追加，需人工检查；不删除半行、不访问真实导航层或数据盘。
        写入异常、用户取消或 worker 停止均由框架 finally 释放写锁；暂停和写入期间取消检查不抛控制异常。

    Time Semantics:
        等锁最多 300 秒且可取消；锁内暂停最多十秒，使用 reporter.wait 的单调等待并维持进度补写。
        核对与追加之间始终持同一把锁，写完放锁后显式 check_cancelled 才返回执行器。
    """
    raise NotImplementedError
