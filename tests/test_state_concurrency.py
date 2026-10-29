"""状态目录初始化的竞争回归；仅在临时目录通过公开initialize_state验证文件系统行为。"""

import multiprocessing
import stat
import time
from multiprocessing.connection import Connection
from multiprocessing.process import BaseProcess
from multiprocessing.synchronize import Barrier
from pathlib import Path

import pytest

from rdp.infra.config import PlatformConfig
from rdp.infra.state import initialize_state, state_paths


@pytest.mark.parametrize("location", ("ancestor", "root", "logs", "job"))
def test_directory_created_between_check_and_mkdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, location: str
) -> None:
    """另一方在检查后创建目录时初始化成功，不chmod竞争方目录，也不把它计入本次新建。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "祖先/状态"), ("示例：写锁",))
    raced = {
        "ancestor": paths.root.parent,
        "root": paths.root,
        "logs": paths.logs,
        "job": paths.job_logs[0][1],
    }[location]
    mkdir, chmod = Path.mkdir, Path.chmod
    inserted = False
    changed: list[Path] = []

    def create(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        nonlocal inserted
        if path == raced and not inserted:
            inserted = True
            mkdir(path, mode=0o755)
            chmod(path, 0o755)
        mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    def record_chmod(path: Path, mode: int, *, follow_symlinks: bool = True) -> None:
        changed.append(path)
        chmod(path, mode, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "mkdir", create)
    monkeypatch.setattr(Path, "chmod", record_chmod)
    assert initialize_state(paths) == ()
    assert inserted and raced not in changed
    assert stat.S_IMODE(raced.stat().st_mode) == 0o755
    for directory in (paths.root.parent, paths.root, paths.logs, paths.job_logs[0][1]):
        assert directory.is_dir() and not directory.is_symlink()
        assert stat.S_IMODE(directory.stat().st_mode) == (0o755 if directory == raced else 0o700)
    assert not paths.database.exists() and not paths.worker_lock.exists()


@pytest.mark.parametrize("kind", ("file", "symlink", "dangling"))
def test_creation_collision_rejects_non_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """竞争窗口出现普通文件仍报NotADirectoryError，真实/悬空软链接仍拒绝且不修改其目标。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ("示例：写锁",))
    raced = paths.job_logs[0][1]
    other = tmp_path / "其他目录"
    other.mkdir(mode=0o755)
    other.chmod(0o755)
    mkdir = Path.mkdir

    def collide(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == raced:
            if kind == "file":
                path.write_text("既有内容")
            else:
                path.symlink_to(other if kind == "symlink" else tmp_path / "不存在")
        mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", collide)
    expected = NotADirectoryError if kind == "file" else ValueError
    with pytest.raises(expected) as caught:
        initialize_state(paths)
    assert str(raced) in str(caught.value)
    assert stat.S_IMODE(other.stat().st_mode) == 0o755
    assert list(other.iterdir()) == []
    if kind == "file":
        assert raced.read_text() == "既有内容"
    else:
        assert raced.is_symlink()


# 四个独立解释器同时初始化；屏障最多等五秒，结果共享十秒总预算，回收每步最多两秒。
_PROCESS_COUNT = 4
_BARRIER_TIMEOUT_S = 5.0
_FINISH_TIMEOUT_S = 10.0
_REAP_TIMEOUT_S = 2.0


def _initialize_from_process(root: Path, barrier: Barrier, result: Connection) -> None:
    """子进程仅在屏障后初始化同一临时状态树，把成功或异常发回父进程。"""
    try:
        paths = state_paths(PlatformConfig(state_dir=root), ("示例：写锁", "转换"))
        barrier.wait(timeout=_BARRIER_TIMEOUT_S)
        result.send(("ok", initialize_state(paths)))
    except BaseException as error:
        result.send(("error", repr(error)))
    finally:
        result.close()


def _reap_processes(processes: list[BaseProcess]) -> None:
    """结束所有未完成的子进程，有界join，必要时kill，最后释放进程句柄。"""
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        if process.pid is not None:
            process.join(timeout=_REAP_TIMEOUT_S)
        if process.is_alive():
            process.kill()
            process.join(timeout=_REAP_TIMEOUT_S)
    alive = [process for process in processes if process.is_alive()]
    for process in processes:
        if process not in alive:
            process.close()
    assert not alive, "子进程未能在回收预算内退出"


def test_initialize_state_concurrent_processes(tmp_path: Path) -> None:
    """四个进程经过同一屏障并发初始化新目录，全部成功且所有新建祖先/目标权限为0700。"""
    root = tmp_path / "新祖先/状态"
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(_PROCESS_COUNT)
    processes: list[BaseProcess] = []
    connections: list[Connection] = []
    readers: list[Connection] = []
    try:
        for _ in range(_PROCESS_COUNT):
            reader, writer = context.Pipe(duplex=False)
            connections.extend((reader, writer))
            readers.append(reader)
            process = context.Process(target=_initialize_from_process, args=(root, barrier, writer))
            processes.append(process)
            process.start()
            writer.close()
        deadline = time.monotonic() + _FINISH_TIMEOUT_S
        results: list[object] = []
        for reader in readers:
            assert reader.poll(max(0.0, deadline - time.monotonic())), "初始化结果等待超时"
            results.append(reader.recv())
        for process in processes:
            process.join(timeout=max(0.0, deadline - time.monotonic()))
            assert not process.is_alive() and process.exitcode == 0
        assert results == [("ok", ())] * _PROCESS_COUNT, results
    finally:
        for connection in connections:
            connection.close()
        _reap_processes(processes)
    for directory in (
        root.parent,
        root,
        root / "logs",
        root / "logs/示例：写锁",
        root / "logs/转换",
    ):
        assert directory.is_dir() and not directory.is_symlink()
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_collision_without_remaining_directory_is_not_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """mkdir报已存在但重新核验时路径已消失，必须保留FileExistsError，不能伪报初始化成功。"""
    paths = state_paths(PlatformConfig(state_dir=tmp_path / "state"), ())
    mkdir = Path.mkdir
    failure = FileExistsError("模拟竞争对象已被删除")

    def disappeared(
        path: Path, mode: int = 0o777, parents: bool = False, exist_ok: bool = False
    ) -> None:
        if path == paths.root:
            raise failure
        mkdir(path, mode=mode, parents=parents, exist_ok=exist_ok)

    monkeypatch.setattr(Path, "mkdir", disappeared)
    with pytest.raises(FileExistsError) as caught:
        initialize_state(paths)
    assert caught.value is failure
    assert not paths.root.exists()
