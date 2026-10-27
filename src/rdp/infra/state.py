"""基础层的状态目录布局与初始化，仅依赖 config，不依赖 logging 或入口层。

依据 M0 spec S1、工单 03 和 ADR 0005；路径操作使用 pathlib/os，权限使用标准库。
只管理平台状态目录，不读写导航层或存储根，不建数据库、不拿 worker 锁、不写作业日志。
"""

import logging
import os
import stat
import unicodedata
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
        navigation_example: 由 root 派生的示例文件绝对路径，只有示例写锁作业可追加。
    """

    root: Path
    database: Path
    logs: Path
    job_logs: tuple[tuple[str, Path], ...]
    worker_lock: Path

    @property
    def navigation_example(self) -> Path:
        """示例写锁文件 root/navigation-example.jsonl 的绝对路径，只计算、不创建。"""
        raise NotImplementedError


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
    seen: set[str] = set()
    for name in job_types:
        if (
            not name
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or any(unicodedata.category(character) == "Cc" for character in name)
        ):
            raise ValueError(f"作业类型实际 {name!r}；期望不含控制字符的单个路径分量")
        if name in seen:
            raise ValueError(f"作业类型实际 {name!r} 重复；期望不重复的作业类型")
        seen.add(name)
    root = config.state_dir
    logs = root / "logs"
    return StatePaths(
        root,
        root / DATABASE_FILENAME,
        logs,
        tuple((name, logs / name) for name in job_types),
        root / WORKER_LOCK_FILENAME,
    )


@dataclass(frozen=True)
class DirectoryPermissionWarning:
    """启动时发现的既有目录权限快照，供日志就绪后报告。

    Attributes:
        path: 已存在的状态根、logs 或作业日志目录的绝对路径；无单位，必填，无默认值。
        mode: POSIX 权限位，整数 0 至 0o7777，且 mode & 0o077 非零；必填，无默认值。
    """

    path: Path
    mode: int


def initialize_state(paths: StatePaths) -> tuple[DirectoryPermissionWarning, ...]:
    """创建缺失的状态目录，并保留全部既有内容和权限。

    Args:
        paths: state_paths 返回的完整布局，无单位；调用方不手工拼接或修改字段。
            使用本地可信状态位置；调用期间不允许其他主体替换路径。

    Returns:
        不可变的宽权限目录快照元组，按 root、logs、job_logs 输入顺序排列；
        仅包含调用前已存在且 mode & 0o077 非零的目标目录，不含祖先或本次新建目录；
        无宽权限目录时为空。成功后所有目标目录存在且可写、可搜索；
        已有内容和权限不改动，不主动更改时间戳。

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
        全部已存在时只检查，第二次调用不写任何东西（验收 2），仍返回当前宽权限清单。
        不直接打警告；调用方在 configure_logging 完成后把返回值交给 log_state_warnings，
        由启动边界记录路径、八进制权限及可能泄露口令哈希的后果（P4）。

    Time Semantics:
        启动阶段同步执行，无重试；先检查已有目标，再逐层创建。
        权限检查只代表调用时刻，不承诺抵御并发恶意路径替换。
    """
    directories = (paths.root, paths.logs, *(path for _, path in paths.job_logs))
    warnings: list[DirectoryPermissionWarning] = []
    for directory in directories:
        # 只对平台直接管理的目标拒绝软链接；祖先属于调用方选择的可信本地路径。
        if directory.is_symlink():
            raise ValueError(f"状态目录不得是软链接：{directory}")
        info = _directory_stat(directory)
        if info is not None:
            mode = stat.S_IMODE(info.st_mode)
            if mode & 0o077:
                warnings.append(DirectoryPermissionWarning(directory, mode))
    for directory in directories:
        _create_directory(directory)
    return tuple(warnings)


def _create_directory(path: Path) -> None:
    """逐层创建，确保祖先也采用平台权限，不依赖 mkdir(parents=True) 的默认权限。"""
    if _directory_stat(path) is not None:
        return
    _create_directory(path.parent)
    path.mkdir(mode=STATE_DIRECTORY_MODE)
    path.chmod(STATE_DIRECTORY_MODE)


def _directory_stat(path: Path) -> os.stat_result | None:
    """区分缺失和外部失败，禁止把普通文件误当成已就绪目录。"""
    try:
        info = path.stat()
    except FileNotFoundError:
        return None
    if not stat.S_ISDIR(info.st_mode):
        raise NotADirectoryError(f"所需路径不是目录：{path}")
    if not os.access(path, os.W_OK | os.X_OK):
        raise PermissionError(f"目录不可写或不可搜索：{path}")
    return info
