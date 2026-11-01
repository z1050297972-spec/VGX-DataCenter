"""入库的隔离存储访问（worker 子进程，M2-05）。

标准库 dir_fd/O_NOFOLLOW 固定根内的父目录；复用第 02 张 RENAME_NOREPLACE。
所有目录读取和改名放在可回收的限时子进程，避免 NAS 阻塞占住 worker 线程。
"""

import json
import os
import stat
import sys
from collections.abc import Generator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import cast

from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_receipt import Receipt
from rdp.jobs.downloads.job import _rename_noreplace  # pyright: ignore[reportPrivateUsage]  # 理由：工单明确要求复用第 02 张的不覆盖改名。
from rdp.jobs.downloads.plan import (
    _file_parts,  # pyright: ignore[reportPrivateUsage]  # 理由：复用第 01 张唯一的仓库文件路径规则。
    _target_parts,  # pyright: ignore[reportPrivateUsage]  # 理由：工单要求入库位置沿用 target_subdir 规则。
)

# 与现有 meta/info.json 读取预算相同，不把大文件读进内存。
MAX_META_BYTES = 4 * 1024 * 1024
_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


@contextmanager
def _directory(root: Path, parts: tuple[str, ...], *, create: bool = False) -> Generator[int]:
    """逐层持有真实目录描述符，不跟随任何软链接。"""
    fd = os.open(root, _FLAGS)
    try:
        for part in parts:
            if create:
                with suppress(FileExistsError):
                    os.mkdir(part, dir_fd=fd)
            child = os.open(part, _FLAGS, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


def _file(root: Path, parts: tuple[str, ...]) -> tuple[int, os.stat_result]:
    """只打开普通文件，路径逐段确认后再读取。"""
    with _directory(root, parts[:-1]) as parent:
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode):
        os.close(fd)
        raise ValueError("清单项目不是普通文件")
    return fd, info


def _check(root: Path, stage: str, target: str, receipt: Receipt) -> JsonObject:
    """检查暂存结构、每个文件大小和不存在的目标；不创建任何目录。"""
    stage_parts = _target_parts(stage)
    with _directory(root, stage_parts) as stage_fd:
        identity = os.fstat(stage_fd)
    try:
        with _directory(root, _target_parts(target)[:-1]) as parent:
            try:
                os.stat(_target_parts(target)[-1], dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise ValueError("目标路径已存在")
    except FileNotFoundError:
        pass
    # 先给出格式诊断，缺 meta/info.json 不会被误称作普通文件缺失。
    fd, _ = _file(root, (*stage_parts, "meta", "info.json"))
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(MAX_META_BYTES + 1)
    if len(raw) > MAX_META_BYTES:
        raise ValueError("meta/info.json 超过读取预算")
    loaded = cast(object, json.loads(raw))
    if not isinstance(loaded, dict):
        raise ValueError("meta/info.json 顶层必须是对象")
    metadata = cast(JsonObject, loaded)
    if not isinstance(metadata.get("codebase_version"), str):
        raise ValueError("不是 LeRobot：缺少 codebase_version")
    size = 0
    for file in receipt.files:
        fd, info = _file(root, (*stage_parts, *_file_parts(file.path)))
        os.close(fd)
        if info.st_size != file.size_bytes:
            raise ValueError(
                f"清单文件大小不一致：{file.path}，实际 {info.st_size}，预期 {file.size_bytes}"
            )
        size += info.st_size
    return {
        "metadata": metadata,
        "size_bytes": size,
        "dev": identity.st_dev,
        "ino": identity.st_ino,
    }


def _move(root: Path, source: str, target: str) -> None:
    """两端固定父目录后复用内核不覆盖改名；绝不通过路径竞态跟随新软链接。"""
    before, after = _target_parts(source), _target_parts(target)
    with _directory(root, before[:-1]) as src, _directory(root, after[:-1], create=True) as dst:
        info = os.stat(before[-1], dir_fd=src, follow_symlinks=False)
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("暂存目标不是普通目录")
        # /proc/self/fd 指向本进程持有的目录，沿用已有 renameat2 的不覆盖保证。
        _rename_noreplace(
            Path(f"/proc/self/fd/{src}") / before[-1], Path(f"/proc/self/fd/{dst}") / after[-1]
        )
        os.fsync(src)
        os.fsync(dst)


def _restore(root: Path, stage: str, target: str, marker: Path) -> None:
    """只退回本次改名的 inode；目标碰撞或外部修改时保留恢复记录等待处理。"""
    identity = json.loads(marker.read_bytes())
    expected = (identity["dev"], identity["ino"])
    try:
        with _directory(root, _target_parts(stage)) as fd:
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == expected:
                return
    except FileNotFoundError:
        pass
    with _directory(root, _target_parts(target)) as fd:
        info = os.fstat(fd)
        if (info.st_dev, info.st_ino) != expected:
            raise ValueError("正式目录身份变化，拒绝退回其他数据")
    _move(root, target, stage)


def _main() -> int:
    """仅接收 worker 构造的命令；诊断作为小 JSON 返回，外层决定异常类别。"""
    action, root, source, target, receipt_path = sys.argv[1:]
    try:
        if action == "check":
            receipt = Receipt.model_validate_json(Path(receipt_path).read_bytes())
            result = _check(Path(root), source, target, receipt)
        elif action == "restore":
            _restore(Path(root), source, target, Path(receipt_path))
            result = {}
        else:
            _move(Path(root), source, target)
            result = {}
    except (OSError, ValueError) as error:
        sys.stdout.write(json.dumps({"error": str(error)}, ensure_ascii=False))
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
