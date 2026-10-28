"""运维入口的公共装配（11），只组合配置、状态、日志、数据库和作业能力。

复用已有注册表、调度及存储适配器；不 import rdp.api，Web 适配由更外层 rdp.cli 注入。
不自建依赖容器；下列不可变对象只表示一次服务启动所需的明确输入和资源。
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sqlalchemy import Engine

from rdp.infra.config import LoadedConfig
from rdp.infra.logging import LoggingSettings, LogTime
from rdp.infra.state import StatePaths
from rdp.infra.storage import LinuxMountSource, MountInspector
from rdp.infra.version import DeploymentLayout
from rdp.jobs.registry import JobRegistry
from rdp.jobs.scheduling_types import SchedulingCatalog
from rdp.jobs.types import JobClock


@dataclass(frozen=True)
class RuntimeInputs:
    """进程边界显式提供的系统依赖；测试全部指向临时路径或内存替身。

    Attributes:
        environ: 环境快照；配置仅识别 RDP_CONFIG，不增加环境配置项。
        home: 当前用户 home 绝对路径；测试必须提供临时目录。
        layout: 包位置推导的部署布局，不用 cwd。
        clock: UTC 墙钟与单调秒时钟；非法返回值属于 DefectError。
        log_time: 日志时钟与本地日历规则；测试无需修改全局 TZ。
        localtime: 系统规则时区文件绝对路径，生产为 /etc/localtime。
        mounts: 系统挂载信息来源；测试使用临时 mountinfo 和 UUID 目录。
        which: shutil.which 或替身；只定位命令，不运行 GPU 探测。
        package_version: importlib.metadata.version 或替身；只查询 rdp 元数据。
    """

    environ: Mapping[str, str]
    home: Path
    layout: DeploymentLayout
    clock: JobClock
    log_time: LogTime
    localtime: Path
    mounts: LinuxMountSource
    which: Callable[[str], str | None]
    package_version: Callable[[str], str]


@dataclass(frozen=True)
class ServiceRuntime:
    """一个服务拥有的资源；生产入口负责在所有使用者退出之后释放引擎。

    Attributes:
        loaded: 已校验配置与来源信息。
        paths: 已初始化的状态目录布局，绝对路径。
        logging: 本进程日志设置，stderr 与 --no-stderr 相反。
        engine: 已核对版本的受管 SQLite 引擎，不允许无数据库模式。
        registry: 完整 production_registry，已核验声明的存储根名字。
        scheduling: 两个服务采用同一构造规则的调度目录。
        inspector: 只读挂载表的检查器；Web 不访问存储根内容。
        version: 本次启动的版本文字，1-128 个码点。
    """

    loaded: LoadedConfig
    paths: StatePaths
    logging: LoggingSettings
    engine: Engine
    registry: JobRegistry
    scheduling: SchedulingCatalog
    inspector: MountInspector
    version: str


def prepare_service(
    process: Literal["web", "worker"], *, no_stderr: bool, inputs: RuntimeInputs
) -> ServiceRuntime:
    """校验并装配一个生产服务的公共资源，成功后交出引擎所有权。

    Args:
        process: web 或 worker，决定活动日志文件名。
        no_stderr: True 只写文件；False 同时向终端输出运行日志。
        inputs: 显式系统依赖；时钟必须有效，所有路径为绝对路径。

    Returns:
        已初始化的服务资源；尚未监听端口、安装信号或启动工作线程。

    Raises:
        ValueError: load_config、state_paths 或 configure_logging 拒绝配置、路径或日志时间。
        OSError: 配置、状态目录、日志或时区规则读写失败，保留原路径及原因。
        InputError: 数据库缺失/版本不匹配，明确提示 rdp migrate；或版本文件、调度/存储登记不合法。
        ConflictError: 数据库版本检查锁冲突。
        ExternalError: 数据库、构建信息或系统挂载来源初始化 I/O 失败。
        DefectError: 注入时钟无效、注册表或受管引擎配置错误。

    Side Effects:
        load_config 后建立基础状态目录，配置 LoggingSettings 并 configure_logging；
        用 log_config_source/log_state_warnings 记录来源和目录权限警告，再建引擎并
        check_database_version，绝不自动迁移；显式配置文件来源另记安全路径，不记录配置内容。
        production_registry 完成所有类型登记后 validate_storage_roots，再补齐各类型日志目录；
        两次 initialize_state 返回的权限警告按路径去重，每个路径只报告一次。
        SchedulingCatalog 使用 resolve_scheduling、production_schedules、local_timezone(inputs.localtime)。
        MountInspector 绑定配置根、mounts 两个读取方法和 UTC 时钟；不调用 read_storage_root。
        初始化失败关闭已建引擎；已建目录和日志保留供排查，不修改配置文件或目录原有权限。

    Time Semantics:
        必须在接收请求或领取作业前完成；SQLite 版本读取锁预算沿用约 5 秒。
        版本、配置和调度时区每次启动取一次；不轮询、不自动重试。
    """
    raise NotImplementedError


def resolve_nvidia_smi(inputs: RuntimeInputs, *, gpus: tuple[int, ...]) -> Path | None:
    """为配置了 GPU 的 worker 定位必需的绝对命令路径。

    Args:
        inputs: 提供可注入 which 的运行输入，不读取额外配置项。
        gpus: 已校验的非负且无重复 GPU 编号元组，可为空。

    Returns:
        空卡列表直接返回 None 且不查 PATH；否则返回 which 找到并解析后的绝对 Path。

    Raises:
        InputError: 配了卡却找不到 nvidia-smi，或 which 返回相对路径；诊断说明安装工具或设置 gpus=[]。
        ExternalError: 定位路径时发生文件系统错误。
        DefectError: which 回调异常或返回非字符串值。

    Side Effects:
        无（只定位命令，不执行它，也不在测试里探测真实 GPU）。

    Time Semantics:
        worker 启动一次；逐卡的 5 秒硬件验证仍由 run_worker 负责。
    """
    raise NotImplementedError
