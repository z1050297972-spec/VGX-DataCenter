"""存储身份与访问契约清单（10、验收1），系统读取与时钟全部替换。"""

import logging
import os
import stat
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread, current_thread
from typing import cast
from unittest.mock import Mock

import pytest

from rdp.infra.config import StorageConfig, StorageRootConfig
from rdp.infra.diagnostics import DefectError, ExternalError
from rdp.infra.storage import (
    DeviceNumber,
    LinuxMountSource,
    MountInspector,
    OfflineReason,
    StorageAccessChecker,
    parse_mountinfo,
    read_storage_root,
)

NOW = datetime(2026, 10, 27, 12, tzinfo=UTC)
UUID = "12345678-1234-1234-1234-123456789abc"


def _line(
    path: Path, *, device: str = "8:1", filesystem: str = "ext4", source: str = "/dev/alias"
) -> str:
    """合成独立挂载表记录，不读取真实系统状态。"""
    return f"20 1 {device} / {path} rw shared:2 - {filesystem} {source} rw\n"


def _setup(tmp_path: Path) -> tuple[MountInspector, Mock, Mock]:
    """根、系统读取和时钟全部限定在测试输入。"""
    root = StorageRootConfig(name="disk", path=tmp_path / "disk", uuid=UUID)
    read = Mock(return_value=_line(root.path))
    resolve = Mock(return_value=DeviceNumber(8, 1))
    return MountInspector((root,), read, resolve, lambda: NOW), read, resolve


def test_online(tmp_path: Path) -> None:
    """验收1：替换挂载表的精确挂载点、ext4设备号与UUID一致返回在线、无原因，结束时刻来自注入UTC时钟。"""
    inspector, read, resolve = _setup(tmp_path)
    result = inspector.inspect()
    assert len(result) == 1
    assert (result[0].name, result[0].path, result[0].writable) == (
        "disk",
        tmp_path / "disk",
        False,
    )
    assert result[0].online and result[0].reason is None and result[0].checked_at == NOW
    read.assert_called_once_with()
    resolve.assert_called_once_with(UUID)


def test_not_mounted(tmp_path: Path) -> None:
    """验收1：无精确挂载点或仅父路径挂载返回没挂载，不对根目录或UUID做无关访问。"""
    inspector, read, resolve = _setup(tmp_path)
    for text in ("", _line(tmp_path)):
        read.return_value = text
        result = inspector.inspect()[0]
        assert not result.online and result.reason is OfflineReason.NOT_MOUNTED
    resolve.assert_not_called()


def test_wrong_source(tmp_path: Path) -> None:
    """验收1：挂载点相同但设备号不同返回挂错了盘，保留根名字、路径和写许可。"""
    inspector, _, resolve = _setup(tmp_path)
    resolve.return_value = DeviceNumber(8, 2)
    result = inspector.inspect()[0]
    assert not result.online and result.reason is OfflineReason.SOURCE_MISMATCH
    assert (result.name, result.path, result.writable) == ("disk", tmp_path / "disk", False)


def test_timeout_warns_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验收1：可释放的替换挂载表读取阻塞耗尽预算，返回超时并恰好一条WARNING，含storage_root、timeout_s和后果。"""
    inspector, _, _ = _setup(tmp_path)
    release = Event()
    threads: list[Thread] = []

    def blocked() -> str:
        """可被finally释放的系统读取，不把真实NFS阻塞带入测试。"""
        threads.append(current_thread())
        assert release.wait(2)
        return ""

    checker = StorageAccessChecker(
        replace(inspector, read_mountinfo=blocked), StorageConfig(access_timeout_s=0.1), Mock()
    )
    try:
        with caplog.at_level(logging.WARNING):
            result = checker.check("disk", checkpoint=lambda: None)
        assert not result.online and result.reason is OfflineReason.TIMEOUT
        assert result.checked_at == NOW
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert len(warnings) == 1
        assert "storage_root=disk" in warnings[0].message and "timeout_s=0.1" in warnings[0].message
        assert "离线" in warnings[0].message
    finally:
        release.set()
        for thread in threads:
            thread.join(1)
            assert not thread.is_alive()


def test_octal_escapes() -> None:
    """验证挂载点与来源解码空格、tab、换行和反斜杠四种八进制转义，只解码一次，不吞特殊字符。"""
    records = parse_mountinfo(
        r"20 1 8:1 / /fake/a\040b\011c\012d\134040 rw - nfs host:/e\040f\134040 rw" + "\n"
    )
    assert records[0].mount_point == Path("/fake/a b\tc\nd\\040")
    assert records[0].source == "host:/e f\\040"


def test_stacked_mounts(tmp_path: Path) -> None:
    """验证同挂载点最后一条覆盖前一条，最后行的错误来源不能被较早正确来源掩盖，返回顺序按最后出现行。"""
    inspector, read, _ = _setup(tmp_path)
    read.return_value += _line(tmp_path / "other") + _line(tmp_path / "disk", device="8:2")
    records = parse_mountinfo(read.return_value)
    assert [item.mount_point for item in records] == [tmp_path / "other", tmp_path / "disk"]
    assert records[-1].device == DeviceNumber(8, 2)
    assert inspector.inspect()[0].reason is OfflineReason.SOURCE_MISMATCH


def test_mountinfo_optional_fields() -> None:
    """验证通过独立分隔符定位fstype和source，允许可选字段、结尾换行及空表。"""
    for options in ("", "shared:1 ", "shared:1 master:2 propagate_from:3 "):
        records = parse_mountinfo(f"20 1 8:1 / /fake rw {options}- ext4 /dev/a rw\n")
        assert len(records) == 1
        assert (records[0].filesystem, records[0].source) == ("ext4", "/dev/a")
    assert parse_mountinfo("") == ()


def test_malformed_mountinfo() -> None:
    """验证缺列、无分隔符、非整数或负设备号、相对挂载点、非法转义均拒绝整表，不跳过坏行。"""
    valid = "20 1 8:1 / /fake rw - ext4 /dev/a rw\n"
    bad = (
        "20 -",
        valid.replace(" - ", " "),
        valid.replace("8:1", "x:1"),
        valid.replace("8:1", "-8:1"),
        valid.replace("8:1", "8:-1"),
        valid.replace("/fake", "relative"),
        valid.replace("/fake", r"/bad\041"),
        valid.replace("/dev/a", r"/bad\999"),
    )
    for text in bad:
        with pytest.raises(ValueError):
            parse_mountinfo(valid + text)


def test_device_aliases(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证通过st_rdev的major/minor比较身份，设备节点别名不同但设备号相同仍在线。"""
    inspector, read, _ = _setup(tmp_path)
    original = Path.stat
    calls: list[Path] = []

    def device_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        """只替换临时UUID节点的系统stat边界。"""
        if path == tmp_path / UUID:
            calls.append(path)
            return cast(os.stat_result, Mock(st_mode=stat.S_IFBLK, st_rdev=os.makedev(8, 1)))
        return original(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", device_stat)
    source = LinuxMountSource(uuid_directory=tmp_path)
    inspector = replace(inspector, resolve_uuid_device=source.resolve_uuid_device)
    for alias in ("/dev/sda", "/dev/mapper/different"):
        read.return_value = _line(tmp_path / "disk", source=alias)
        assert inspector.inspect()[0].online
    assert calls == [tmp_path / UUID, tmp_path / UUID]


def test_missing_uuid(tmp_path: Path) -> None:
    """验证UUID链接不存在、断链、非块设备返回无设备，检查结果是挂错了盘而非在线。"""
    inspector, _, _ = _setup(tmp_path)
    adapter = LinuxMountSource(uuid_directory=tmp_path)
    inspector = replace(inspector, resolve_uuid_device=adapter.resolve_uuid_device)
    target = tmp_path / UUID
    for kind in ("absent", "broken", "file"):
        if kind == "broken":
            target.symlink_to(tmp_path / "absent")
        elif kind == "file":
            target.unlink()
            target.write_text("regular", encoding="utf-8")
        assert adapter.resolve_uuid_device(UUID) is None
        assert inspector.inspect()[0].reason is OfflineReason.SOURCE_MISMATCH


def test_wrong_filesystem(tmp_path: Path) -> None:
    """验证UUID来源要求ext4，即使设备号相同但fstype不是ext4也离线。"""
    inspector, read, _ = _setup(tmp_path)
    for filesystem in ("xfs", "nfs", "tmpfs"):
        read.return_value = _line(tmp_path / "disk", filesystem=filesystem)
        assert inspector.inspect()[0].reason is OfflineReason.SOURCE_MISMATCH


def test_nfs_identity(tmp_path: Path) -> None:
    """验证nfs/nfs4来源逐字匹配才在线，其他fstype或来源差异离线，NFS从不调用UUID查询。"""
    inspector, read, resolve = _setup(tmp_path)
    root = StorageRootConfig(name="nas", path=tmp_path / "nas", nfs_export="host:/share")
    inspector = replace(inspector, roots=(root,))
    for filesystem, source, online in (
        ("nfs", "host:/share", True),
        ("nfs4", "host:/share", True),
        ("ext4", "host:/share", False),
        ("nfs", "host:/share/", False),
        ("nfs", "alias:/share", False),
    ):
        read.return_value = _line(root.path, filesystem=filesystem, source=source)
        result = inspector.inspect()[0]
        assert result.online is online
        assert result.reason is (None if online else OfflineReason.SOURCE_MISMATCH)
    resolve.assert_not_called()


def test_mount_table_io_failure(tmp_path: Path) -> None:
    """验证读挂载表抛OSError转ExternalError，保留异常链及根名、规则、实际、后果、下一步，不暴露表原文。"""
    inspector, read, _ = _setup(tmp_path)
    failure = PermissionError(13, "private-table-content")
    read.side_effect = failure
    with pytest.raises(ExternalError) as caught:
        inspector.inspect()
    assert caught.value.__cause__ is failure
    diagnostic = caught.value.diagnostics[0]
    assert diagnostic.rule == "storage.mount_table"
    assert any(item.key == "storage_root" and item.value == "disk" for item in diagnostic.objects)
    assert "PermissionError" in diagnostic.actual and "13" in diagnostic.actual
    assert diagnostic.consequence and diagnostic.next_step and diagnostic.expected
    assert "private-table-content" not in diagnostic.model_dump_json()


def test_mount_table_parse_failure(tmp_path: Path) -> None:
    """验证损坏表在检查边界转ExternalError且不捏造没挂载或部分成功状态。"""
    inspector, read, _ = _setup(tmp_path)
    read.return_value += "broken-private-record"
    with pytest.raises(ExternalError) as caught:
        inspector.inspect()
    assert isinstance(caught.value.__cause__, ValueError)
    assert caught.value.diagnostics[0].rule == "storage.mount_table"
    assert "broken-private-record" not in caught.value.diagnostics[0].model_dump_json()


def test_uuid_io_failure(tmp_path: Path) -> None:
    """验证UUID查询权限或其他I/O失败转ExternalError，诊断storage.uuid_device而非误报挂错盘。"""
    inspector, _, resolve = _setup(tmp_path)
    failure = PermissionError(13, "blocked")
    resolve.side_effect = failure
    with pytest.raises(ExternalError) as caught:
        inspector.inspect()
    assert caught.value.__cause__ is failure
    assert caught.value.diagnostics[0].rule == "storage.uuid_device"
    assert caught.value.diagnostics[0].objects[0].value == "disk"


def test_invalid_dependencies(tmp_path: Path) -> None:
    """验证非配置根、错误回调返回值、非法设备号和非I/O回调异常归DefectError。"""
    inspector, _, _ = _setup(tmp_path)
    for broken in (
        replace(inspector, roots=cast(tuple[StorageRootConfig, ...], (object(),))),
        replace(inspector, read_mountinfo=Mock(return_value=1)),
        replace(inspector, read_mountinfo=Mock(side_effect=RuntimeError("bug"))),
        replace(inspector, resolve_uuid_device=Mock(return_value="8:1")),
        replace(inspector, resolve_uuid_device=Mock(return_value=DeviceNumber(-1, 0))),
        replace(inspector, resolve_uuid_device=Mock(return_value=DeviceNumber(True, 0))),
        replace(inspector, resolve_uuid_device=Mock(side_effect=ValueError("bug"))),
    ):
        with pytest.raises(DefectError):
            broken.inspect()
    with pytest.raises(DefectError):
        StorageAccessChecker(inspector, StorageConfig(), cast(Callable[[Path], None], None)).check(
            "disk", checkpoint=lambda: None
        )


def test_invalid_clock(tmp_path: Path) -> None:
    """验证naive、非datetime或异常时钟归DefectError，有效偏移统一转UTC，检查时刻取结束而非开始。"""
    inspector, read, _ = _setup(tmp_path)
    for clock in (
        Mock(return_value=NOW.replace(tzinfo=None)),
        Mock(return_value=1),
        Mock(side_effect=RuntimeError("clock")),
    ):
        with pytest.raises(DefectError):
            replace(inspector, clock=clock).inspect()
    moments = [NOW - timedelta(days=1)]

    def read_then_advance() -> str:
        """读取后推进墙钟，使开始时刻与结束时刻有区分度。"""
        moments[0] = datetime(2026, 10, 27, 17, tzinfo=timezone(timedelta(hours=5)))
        return str(read.return_value)

    result = replace(
        inspector, read_mountinfo=read_then_advance, clock=lambda: moments[0]
    ).inspect()[0]
    assert result.checked_at == NOW and result.checked_at.tzinfo is UTC


def test_web_never_reads_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证MountInspector只调用一次表读取和必要UUID元数据查询，不stat根、不返回timeout，顺序同配置。"""
    inspector, read, resolve = _setup(tmp_path)
    second = StorageRootConfig(name="second", path=tmp_path / "second", nfs_export="host:/share")
    inspector = replace(inspector, roots=(second, *inspector.roots))
    read.return_value += _line(second.path, filesystem="nfs4", source="host:/share")
    original = Path.stat

    def no_root_stat(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
        """根目录访问必须由worker承担，Web查询触碰即失败。"""
        assert path not in (second.path, inspector.roots[1].path)
        return original(path, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(Path, "stat", no_root_stat)
    result = inspector.inspect()
    assert [item.name for item in result] == ["second", "disk"]
    assert all(item.online and item.reason is None for item in result)
    read.assert_called_once_with()
    resolve.assert_called_once_with(UUID)


def test_empty_roots() -> None:
    """验证空根配置返回空元组，表读取、设备查询和时钟均不调用。"""
    forbidden = Mock(side_effect=AssertionError("不应检查系统"))
    assert MountInspector((), forbidden, forbidden, forbidden).inspect() == ()
    forbidden.assert_not_called()


def test_linux_adapters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证Linux适配器只读注入临时路径，表用surrogateescape，设备查询只stat指定UUID且不枚举目录。"""
    table = tmp_path / "mountinfo"
    content = b"20 1 8:1 / /fake/\xff rw - ext4 /dev/a rw\n"
    table.write_bytes(content)
    adapter = LinuxMountSource(table, tmp_path)
    assert adapter.read_mountinfo().encode("utf-8", errors="surrogateescape") == content
    assert parse_mountinfo(adapter.read_mountinfo())[0].mount_point == Path("/fake/\udcff")
    monkeypatch.setattr(Path, "iterdir", Mock(side_effect=AssertionError("不得遍历")))
    assert adapter.resolve_uuid_device(UUID) is None
    table.unlink()
    with pytest.raises(FileNotFoundError):
        adapter.read_mountinfo()


def test_invalid_adapter_paths(tmp_path: Path) -> None:
    """验证系统适配器路径相对、含NUL/..或UUID穿越报DefectError，在读取前拒绝。"""
    for path in (Path("relative"), tmp_path / ".." / "table", Path(str(tmp_path) + "/x\x00")):
        with pytest.raises(DefectError):
            LinuxMountSource(mountinfo_path=path).read_mountinfo()
        with pytest.raises(DefectError):
            LinuxMountSource(uuid_directory=path).resolve_uuid_device(UUID)
    for uuid in ("../bad", "", UUID.upper()):
        with pytest.raises(DefectError):
            LinuxMountSource(uuid_directory=tmp_path).resolve_uuid_device(uuid)


def test_root_access_order(tmp_path: Path) -> None:
    """验证worker只在挂载身份通过后调用一次根stat，没挂载或挂错盘时不访问根。"""
    inspector, read, resolve = _setup(tmp_path)
    inspector.roots[0].path.mkdir()

    def access(path: Path) -> None:
        """真实临时根stat之前必须已经核对挂载身份。"""
        assert read.call_count == 1 and resolve.call_count == 1
        read_storage_root(path)

    probe = Mock(side_effect=access)
    checker = StorageAccessChecker(inspector, StorageConfig(), probe)
    assert checker.check("disk", checkpoint=lambda: None).online
    probe.assert_called_once_with(inspector.roots[0].path)
    for text in ("", _line(inspector.roots[0].path, device="8:2")):
        read.return_value = text
        probe.reset_mock()
        assert not checker.check("disk", checkpoint=lambda: None).online
        probe.assert_not_called()
    assert list(inspector.roots[0].path.iterdir()) == []


def test_root_access_errors(tmp_path: Path) -> None:
    """验证根stat的权限、消失和非目录错误转ExternalError，根名及原因可诊断，根下无新文件。"""
    inspector, _, _ = _setup(tmp_path)
    for failure in (
        PermissionError(13, "denied"),
        FileNotFoundError(2, "gone"),
        NotADirectoryError(20, "file"),
    ):
        checker = StorageAccessChecker(inspector, StorageConfig(), Mock(side_effect=failure))
        with pytest.raises(ExternalError) as caught:
            checker.check("disk", checkpoint=lambda: None)
        assert caught.value.__cause__ is failure
        diagnostic = caught.value.diagnostics[0]
        assert diagnostic.objects[0].value == "disk" and type(failure).__name__ in diagnostic.actual
    inspector.roots[0].path.write_text("file", encoding="utf-8")
    with pytest.raises(ExternalError) as caught:
        StorageAccessChecker(inspector, StorageConfig(), read_storage_root).check(
            "disk", checkpoint=lambda: None
        )
    assert isinstance(caught.value.__cause__, NotADirectoryError)
    assert sorted(item.name for item in tmp_path.iterdir()) == ["disk"]
    for path in (Path("relative"), tmp_path / "..", Path(str(tmp_path) + "/bad\x00")):
        with pytest.raises(DefectError):
            read_storage_root(path)


def test_root_access_timeout(tmp_path: Path) -> None:
    """验证根stat阻塞也按超时离线返回，整个检查共享一个预算，UUID阶段耗时不会重置截止。"""
    inspector, _, _ = _setup(tmp_path)
    release = Event()
    threads: list[Thread] = []

    def resolve(uuid: str) -> DeviceNumber:
        """UUID与根访问各用不足总预算的时间，合计超过预算。"""
        assert uuid == UUID
        threads.append(current_thread())
        release.wait(0.07)
        return DeviceNumber(8, 1)

    def access(path: Path) -> None:
        assert path == tmp_path / "disk"
        release.wait(0.07)

    try:
        checker = StorageAccessChecker(
            replace(inspector, resolve_uuid_device=resolve),
            StorageConfig(access_timeout_s=0.1),
            access,
        )
        assert checker.check("disk", checkpoint=lambda: None).reason is OfflineReason.TIMEOUT
    finally:
        release.set()
        for thread in threads:
            thread.join(1)
            assert not thread.is_alive()


@pytest.mark.parametrize("stage", ["table", "uuid"])
def test_late_thread_result(tmp_path: Path, caplog: pytest.LogCaptureFixture, stage: str) -> None:
    """验证超时后线程迟到不改返回结果、不重复警告、不继续调用下一步根访问；测试finally释放并有界回收替身线程。"""
    inspector, read, resolve = _setup(tmp_path)
    release = Event()
    threads: list[Thread] = []
    access = Mock(return_value=None)

    def block() -> None:
        threads.append(current_thread())
        assert release.wait(2)

    def table() -> str:
        block()
        return str(read.return_value)

    def device(uuid: str) -> DeviceNumber:
        assert uuid == UUID
        block()
        return DeviceNumber(8, 1)

    selected = (
        replace(inspector, read_mountinfo=table)
        if stage == "table"
        else replace(inspector, resolve_uuid_device=device)
    )
    try:
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            result = StorageAccessChecker(
                selected, StorageConfig(access_timeout_s=0.1), access
            ).check("disk", checkpoint=lambda: None)
            release.set()
            for thread in threads:
                thread.join(1)
                assert not thread.is_alive()
        assert result.reason is OfflineReason.TIMEOUT and not result.online
        access.assert_not_called()
        if stage == "table":
            resolve.assert_not_called()
        assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 1
    finally:
        release.set()
        for thread in threads:
            thread.join(1)
            assert not thread.is_alive()


def test_daemon_and_bounded_wait(tmp_path: Path) -> None:
    """验证检查线程为daemon、调用方不无限join，等待按单调时钟，不因UTC墙钟回拨延长。"""
    inspector, _, _ = _setup(tmp_path)
    release = Event()
    threads: list[Thread] = []
    wall = [NOW]

    def blocked() -> str:
        threads.append(current_thread())
        wall[0] -= timedelta(days=1)
        assert release.wait(2)
        return ""

    try:
        start = time.monotonic()
        result = StorageAccessChecker(
            replace(inspector, read_mountinfo=blocked, clock=lambda: wall[0]),
            StorageConfig(access_timeout_s=0.1),
            Mock(return_value=None),
        ).check("disk", checkpoint=lambda: None)
        assert time.monotonic() - start < 0.8
        assert result.reason is OfflineReason.TIMEOUT and result.checked_at == NOW - timedelta(
            days=1
        )
        assert len(threads) == 1 and threads[0].daemon and threads[0].is_alive()
    finally:
        release.set()
        for thread in threads:
            thread.join(1)
            assert not thread.is_alive()


def test_unknown_root(tmp_path: Path) -> None:
    """验证worker检查未知名字抛DefectError而非没挂载，不读系统表或根目录。"""
    inspector, read, resolve = _setup(tmp_path)
    access = Mock(return_value=None)
    with pytest.raises(DefectError):
        StorageAccessChecker(inspector, StorageConfig(), access).check(
            "unknown", checkpoint=lambda: None
        )
    read.assert_not_called()
    resolve.assert_not_called()
    access.assert_not_called()


@pytest.mark.parametrize("separator", ["\r", "\x0c", "\x85", "\u2028"])
def test_non_lf_characters_do_not_split_mount_records(tmp_path: Path, separator: str) -> None:
    """无关挂载的原样控制字符不分割记录，系统表读取也保留CR，登记根仍在线。"""
    inspector, read, _ = _setup(tmp_path)
    unrelated = f"21 1 0:2 / /other/a{separator}b rw - fuse host:/a{separator}b rw\n"
    content = str(read.return_value) + unrelated
    table = tmp_path / "mountinfo"
    table.write_bytes(content.encode("utf-8"))
    adapter = LinuxMountSource(mountinfo_path=table, uuid_directory=tmp_path)
    inspector = replace(inspector, read_mountinfo=adapter.read_mountinfo)
    assert inspector.inspect()[0].online
    records = parse_mountinfo(content)
    assert len(records) == 2
    assert records[1].mount_point == Path(f"/other/a{separator}b")
    assert records[1].source == f"host:/a{separator}b"
    assert adapter.read_mountinfo() == content


@pytest.mark.parametrize("filesystem", ["ext4", "nfs4"])
def test_subdirectory_bind_is_source_mismatch(tmp_path: Path, filesystem: str) -> None:
    """即使设备号或NFS来源正确，bind子目录也不是登记的整个文件系统。"""
    inspector, read, _ = _setup(tmp_path)
    root = inspector.roots[0]
    source = "/dev/alias"
    if filesystem == "nfs4":
        root = StorageRootConfig(name="disk", path=root.path, nfs_export="host:/share")
        inspector = replace(inspector, roots=(root,))
        source = "host:/share"
    for mount_root in ("/subdirectory", r"/with\040space"):
        read.return_value = _line(root.path, filesystem=filesystem, source=source).replace(
            " / ", f" {mount_root} ", 1
        )
        result = inspector.inspect()[0]
        assert not result.online and result.reason is OfflineReason.SOURCE_MISMATCH
    read.return_value = _line(root.path, filesystem=filesystem, source=source)
    assert inspector.inspect()[0].online
