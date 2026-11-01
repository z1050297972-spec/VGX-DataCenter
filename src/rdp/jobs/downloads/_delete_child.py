"""有界删除子进程：自身持锁到真正退出，防止卡死 I/O 释放互斥保护。"""

import fcntl
import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select

from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.state import DATABASE_FILENAME
from rdp.jobs.downloads.cleanup import DeleteParameters
from rdp.jobs.downloads.coordination import open_lock
from rdp.jobs.models import JobRow

_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def remove_staging(args: Sequence[str]) -> int:
    """在进程锁内验证作业及并发状态，再安全删除指定暂存目录。

    Args:
        args: 状态根、存储根、作业编号、根名、类型、仓库及提交短码。

    Returns:
        成功返回 0；拒绝或操作失败返回非零。

    Raises:
        无；所有错误只输出固定诊断，不回显输入或异常。

    Side Effects:
        读取状态数据库并删除一个已登记的暂存目录，不跟随符号链接。

    Time Semantics:
        锁持有至本进程完成；父作业负责总超时、取消和进程组回收。
    """
    try:
        return _remove(args)
    except Exception:
        sys.stderr.write("暂存清理失败或存在冲突，请检查作业状态和存储根。\n")
        return 1


def _remove(args: Sequence[str]) -> int:
    """不记录输入；锁内复核数据库后通过目录描述符删除。"""
    state, root, raw_id, root_name, kind, repo, commit = args
    state_path, root_path = Path(state), Path(root)
    parameters = DeleteParameters.model_validate(
        {"storage_root": root_name, "repo_type": kind, "repo_id": repo, "commit_prefix": commit}
    )
    job_id = int(raw_id)
    fd = open_lock(state_path)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        engine = create_database_engine(state_path / DATABASE_FILENAME)
        try:
            with session_scope(engine, read_only=True) as session:
                record = session.get(JobRow, job_id)
                if (
                    record is None
                    or record.type_name != "download_staging_delete"
                    # 作业未领取、已取消或结束时，迟到子进程不能再实施删除。
                    or record.state != "running"
                    or record.submitter_id is None
                    or record.parameters != parameters.model_dump(mode="json")
                ):
                    return 1
                downloads = session.scalars(select(JobRow).where(JobRow.type_name == "download"))
                fields = ("storage_root", "repo_type", "repo_id")
                for row in downloads:
                    if all(
                        row.parameters.get(key) == getattr(parameters, key) for key in fields
                    ) and (row.job_id > job_id or row.state in ("queued", "running", "cancelling")):
                        return 1
        finally:
            engine.dispose()
        if not shutil.rmtree.avoids_symlink_attacks:
            return 1
        namespace, name = parameters.repo_id.split("/")
        descriptors = [os.open(root_path, _FLAGS)]
        try:
            for part in ("暂存", "下载", parameters.repo_type, namespace):
                descriptors.append(os.open(part, _FLAGS, dir_fd=descriptors[-1]))
            shutil.rmtree(f"{name}@{parameters.commit_prefix}", dir_fd=descriptors[-1])
        finally:
            for descriptor in reversed(descriptors):
                os.close(descriptor)
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(remove_staging(sys.argv[1:]))
