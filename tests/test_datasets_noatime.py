"""真实扫描atime回归：只替换打开系统调用，验证标志与EPERM回退，不测真实挂载行为。"""

import errno
import os
from pathlib import Path
from typing import Any

import pytest
from datasets_execution_support import dataset_case
from datasets_storage_support import enable_storage, scan
from nav_manifest import FakeNavigation


def test_storage_opens_request_noatime(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """存储文件和目录打开均请求O_NOATIME，扫描结果仍可发布。"""
    original = os.open
    observed: list[tuple[str, int]] = []
    roots = tuple(root.path for root in fake_nav.storage_roots)

    def opened(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if isinstance(path, (str, Path)) and any(Path(path).is_relative_to(root) for root in roots):
            observed.append((str(path), flags))
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", opened)
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        scan(case)
    assert observed
    assert any(path.endswith("info.json") for path, _ in observed)
    assert any(flags & os.O_DIRECTORY for _, flags in observed)
    assert all(flags & os.O_NOATIME for _, flags in observed)


def test_noatime_eperm_falls_back(
    tmp_path: Path,
    fake_nav: FakeNavigation,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """无CAP_FOWNER时EPERM只回退一次普通打开，文件和目录均不报错、不刷日志。"""
    original = os.open
    attempted: list[tuple[str, int]] = []
    roots = tuple(root.path for root in fake_nav.storage_roots)

    def opened(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if isinstance(path, (str, Path)) and any(Path(path).is_relative_to(root) for root in roots):
            attempted.append((str(path), flags))
            if flags & os.O_NOATIME:
                raise PermissionError(errno.EPERM, "fixture owner mismatch")
        return original(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", opened)
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        result = scan(case)
        assert (
            next(item for item in result.sources if item.entry_path == "按任务/libero_10").fps == 20
        )
    assert attempted and len(attempted) % 2 == 0
    for first, retry in zip(attempted[::2], attempted[1::2], strict=True):
        assert first[0] == retry[0] and first[1] ^ retry[1] == os.O_NOATIME
    assert not any(
        "EPERM" in record.message or "fixture owner" in record.message for record in caplog.records
    )
