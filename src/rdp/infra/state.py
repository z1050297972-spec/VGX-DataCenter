"""基础层的状态目录布局与初始化，仅依赖 config，不依赖 logging 或入口层。

依据 M0 spec S1、工单 03 和 ADR 0005；路径操作使用 pathlib/os，权限使用标准库。
只管理平台状态目录，不读写导航层或存储根，不建数据库、不拿 worker 锁、不写作业日志。
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from rdp.infra.config import PlatformConfig

logger = logging.getLogger(__name__)

# S1 要求集中定义数据库位置；具体 basename 是本票的命名提案，供第 05 张复用。
DATABASE_FILENAME = "rdp.sqlite3"
# ADR 0005 要求 worker 与运维命令共用单实例锁；basename 在本票统一，取锁属于第 08 张。
WORKER_LOCK_FILENAME = "worker.lock"
# 工单 03：数据库以后含口令哈希，新建目录只向属主开放，单位为 POSIX 权限位。
STATE_DIRECTORY_MODE = 0o700


@dataclass(frozen=True)
class StatePaths:
    """平台状态目录中所有位置的不可变值对象，不表示文件已存在。

    Attributes:
        root: 状态根目录绝对 Path，无单位；必填，无默认值。
        database: root/rdp.sqlite3 的绝对 Path，无单位；必填，无默认值。
        logs: root/logs 的绝对 Path，无单位；必填，无默认值。
        job_logs: (作业类型, logs/作业类型的绝对 Path) 元组序列，无单位；
            保持输入顺序、类型不重复，允许为空；必填，无默认值，不使用可变 dict。
        worker_lock: root/worker.lock 的绝对 Path，无单位；必填，无默认值。
    """

    root: Path
    database: Path
    logs: Path
    job_logs: tuple[tuple[str, Path], ...]
    worker_lock: Path


def state_paths(config: PlatformConfig, job_types: Sequence[str]) -> StatePaths:
    """按唯一布局计算所有状态路径，不读取文件系统。

    Args:
        config: 已校验且路径已展开的 PlatformConfig，无单位。
        job_types: 作业类型名序列，无单位；允许空序列，名称为非空单个路径分量，
            可含中文，不可为 . 或 ..，不可含斜杠、反斜杠或控制字符，不可重复。
            清单由第 08 张传入，本票不枚举类型。

    Returns:
        不可变 StatePaths；数据库和锁用具名常量，job_logs 顺序与输入一致；
        空序列得到空 job_logs，所有路径位于 config.state_dir 下。

    Raises:
        ValueError: 作业类型名非法或重复；消息指出实际名称及期望，不返回部分路径。

    Side Effects:
        无。不创建目录或文件，不检查路径存在性，不修改输入。

    Time Semantics:
        无。与工作目录、时钟无关。
    """
    raise NotImplementedError


def initialize_state(paths: StatePaths) -> None:
    """创建缺失的状态目录，并保留全部既有内容和权限。

    Args:
        paths: state_paths 返回的完整布局，无单位；调用方不手工拼接或修改字段。
            使用本地可信状态位置；调用期间不允许其他主体替换路径。

    Returns:
        无。成功后 root、logs 和全部 job_logs 目录存在且可写、可搜索；
        已存在的目录及其文件内容、权限、时间戳均不主动改动。

    Raises:
        NotADirectoryError: 所需目录或祖先被普通文件占用；消息包含冲突路径。
        ValueError: root、logs 或作业日志目录本身是软链接（包括悬空链接）；拒绝跟随。
        PermissionError: 所需目录不可写或不可搜索，或创建/设置新目录权限被拒绝；包含路径。
        OSError: 其他目录检查或创建失败，例如磁盘满；保留路径和原始原因。

    Side Effects:
        从外到内创建缺失祖先、root、logs、job_logs，新建目录最终权限为 0700，
        即使 umask 更严格也只纠正本次新建目录；不改进程 umask、不 chmod 已有目录。
        不创建数据库、锁文件或任何日志文件；不通过试写探测已有目录的权限。
        失败时保留已建空目录，不回滚、不删除任何既有对象，修正原因后可安全重试。
        全部已存在时只检查，第二次调用不写任何东西（验收 2）。

    Time Semantics:
        启动阶段同步执行，无重试；先检查已有目标，再逐层创建。
        权限检查只代表调用时刻，不承诺抵御并发恶意路径替换。
    """
    raise NotImplementedError
