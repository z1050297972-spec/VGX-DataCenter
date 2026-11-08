"""转换入库的隔离检查与报告落盘；NAS 访问只在有界、可回收子进程内。

复用下载的逐层 O_NOFOLLOW 目录能力，检查器和标准库临时文件，不另造文件系统抽象。
"""

import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import cast

from rdp.jobs.conversion._check_child import check, diagnostic
from rdp.jobs.conversion._check_data import MAX_INFO_BYTES
from rdp.jobs.conversion.check_models import CheckLayer, CheckReport
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_child import _directory  # pyright: ignore[reportPrivateUsage] # 理由：复用同根移动的唯一逐层防软链接实现。


def _read(parent: int, name: str) -> JsonObject:
    """只读固定普通 JSON 文件，配置全文受既有4MiB预算约束。"""
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(MAX_INFO_BYTES + 1)
    if len(raw) > MAX_INFO_BYTES:
        raise ValueError("入库元信息超过4MiB")
    return cast(JsonObject, json.loads(raw))


def _failed(reason: str) -> CheckReport:
    """前置转换失败时不访问产物，四层明确标记后续未检查。"""
    return CheckReport(
        result="不通过",
        layers=(
            CheckLayer(name="结构", result="不通过", diagnostics=(diagnostic("结构", reason),)),
            *(CheckLayer(name=name, result="未检查") for name in ("计数", "视频", "内容")),
        ),
    )


def _inspect(root: Path, identifier: str, version: str, valid: bool, scratch: Path) -> JsonObject:
    """固定暂存目录描述符，先校验转换结果，再检查和写报告。"""
    if not identifier.isdecimal() or int(identifier) < 1:
        raise ValueError("转换编号必须为正整数")
    # 转换可能在建立暂存之前失败；仍须落下直接不通过报告，不能继续读产物。
    with _directory(root, ("暂存", "转换", identifier), create=not valid) as fd:
        receipt = _read(fd, "转换回执.json") if valid else {}
        facts: JsonObject = {"receipt": receipt, "size_bytes": None}
        if not valid or receipt.get("exit_code") != 0:
            report = _failed("转换作业未成功或工具退出码不是0")
        else:
            with _directory(fd, ("out",)) as output_fd:
                # 检查器拒绝根软链接，chdir 到持有的真实目录可同时固定根身份。
                os.fchdir(output_fd)
                report = check(Path.cwd(), version, scratch)
                identity = os.fstat(output_fd)
                facts.update(dev=identity.st_dev, ino=identity.st_ino)
                if report.result != "不通过":
                    with _directory(output_fd, ("meta",)) as meta:
                        facts["metadata"] = _read(meta, "info.json")
                    facts["size_bytes"] = _size(Path.cwd())
        _report(fd, report)
        facts["report"] = report.model_dump(mode="json")
        return facts


def _size(root: Path) -> int:
    """只累加普通文件，不跟随任何未被格式检查枚举到的额外软链接。"""
    total = 0
    with os.scandir(root) as entries:
        for entry in entries:
            if entry.is_symlink():
                raise ValueError("产物包含软链接")
            if entry.is_dir(follow_symlinks=False):
                total += _size(Path(entry.path))
            elif entry.is_file(follow_symlinks=False):
                total += entry.stat(follow_symlinks=False).st_size
    return total


def _report(parent: int, report: CheckReport) -> None:
    """原子替换检查报告，重启重跑不留下半截JSON；临时名固定且拒绝链接。"""
    temporary = ".入库检查.tmp"
    fd = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(report.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, "入库检查.json", src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary, dir_fd=parent)


if __name__ == "__main__":
    sys.stdout.write(
        json.dumps(
            _inspect(
                Path(sys.argv[1]), sys.argv[2], sys.argv[3], sys.argv[4] == "1", Path(sys.argv[5])
            )
        )
    )
