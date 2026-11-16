"""G2 输入身份边界只核对临时路径，不解析或伪造工具报告。"""

import os
from pathlib import Path

import pytest

from rdp.infra.diagnostics import InputError
from rdp.jobs.cleaning._g2 import validate_paths


@pytest.mark.parametrize("case", ["duplicate", "directory", "parent", "hardlink", "symlink"])
def test_reject_ambiguous_or_indirect_archives(tmp_path: Path, case: str) -> None:
    """同任务约束之外，重复身份、目录和链接也必须在 CLI 执行前拒绝。"""
    task = tmp_path / "task_42"
    task.mkdir()
    source = task / "a.tar.gz"
    source.touch()
    other = task / "b.tar.gz"
    if case == "duplicate":
        other = source
    elif case == "directory":
        other.mkdir()
    elif case == "parent":
        other = task
    elif case == "hardlink":
        os.link(source, other)
    else:
        other.symlink_to(source)
    with pytest.raises(InputError):
        validate_paths((source, other), filesystem=True)


def test_reject_symlink_in_archive_ancestor(tmp_path: Path) -> None:
    """叶子是普通文件也不能绕过祖先链接边界，不能通过 task 目录链接访问外部归档。"""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "a.tar.gz").touch()
    task = tmp_path / "task_42"
    task.symlink_to(outside, target_is_directory=True)
    with pytest.raises(InputError):
        validate_paths((task / "a.tar.gz",), filesystem=True)
