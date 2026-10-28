"""真实挂载表形状回归，仅读取仓库副本，不读取真实系统挂载表或设备目录。

来源：第10张assets的mountinfo-sample.txt，执行线采集并匿名化的58行原件。
原件SHA256：4ea5a475514e333ba04ef034ef1c532c623a00e8d97f4ba76916b8b968339e9b。
整理仅将第49、50行挂载点的首分量替换成/srv/rdp-test，其余字节保持原样；未截短。
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rdp.infra.config import StorageRootConfig
from rdp.infra.storage import DeviceNumber, MountInspector, OfflineReason, parse_mountinfo

SAMPLE = Path(__file__).parent / "fixtures" / "storage" / "mountinfo-sample.txt"

# 输入仅作为挂载表字段文本，不访问其中的路径或命名空间标识。
_FILESYSTEM_ROOT_CASES = [
    ("/", "/"),
    ("/subdirectory", "/subdirectory"),
    ("mnt:[4026532978]", "mnt:[4026532978]"),
    (r"/with\040space", "/with space"),
    ("-", "-"),
    ("/.", "/."),
]


def test_real_mountinfo_sample_preserves_nsfs_and_online_disks() -> None:
    """58行解析为57个去重挂载点，保留binfmt叠层最后记录，两盘在线且nsfs标识不变。"""
    text = SAMPLE.read_bytes().decode("utf-8")
    records = parse_mountinfo(text)
    assert text.count("\n") == 58 and text.endswith("\n")
    # 原件的binfmt_misc有autofs、binfmt_misc两层；契约规定同点只留最后一条。
    assert len(records) == 57
    binfmt = next(
        record for record in records if record.mount_point == Path("/proc/sys/fs/binfmt_misc")
    )
    assert (binfmt.filesystem, binfmt.device) == ("binfmt_misc", DeviceNumber(0, 48))
    assert {
        record.mount_point.name: record.filesystem_root
        for record in records
        if record.filesystem == "nsfs"
    } == {
        "docker.mnt": "mnt:[4026532978]",
        "prompting-client.mnt": "mnt:[4026532980]",
        "snapd-desktop-integration.mnt": "mnt:[4026532981]",
        "firmware-updater.mnt": "mnt:[4026532775]",
    }
    roots = (
        StorageRootConfig(
            name="dataset1",
            path=Path("/srv/rdp-test/dataset1"),
            uuid="11111111-1111-1111-1111-111111111111",
        ),
        StorageRootConfig(
            name="dataset2",
            path=Path("/srv/rdp-test/dataset2"),
            uuid="22222222-2222-2222-2222-222222222222",
        ),
    )
    devices = {
        "11111111-1111-1111-1111-111111111111": DeviceNumber(8, 0),
        "22222222-2222-2222-2222-222222222222": DeviceNumber(8, 16),
    }
    results = MountInspector(
        roots, lambda: text, devices.__getitem__, lambda: datetime(2026, 10, 27, tzinfo=UTC)
    ).inspect()
    assert [(result.name, result.online, result.reason) for result in results] == [
        ("dataset1", True, None),
        ("dataset2", True, None),
    ]


@pytest.mark.parametrize(("raw_root", "expected"), _FILESYSTEM_ROOT_CASES)
def test_registered_root_requires_exact_slash(raw_root: str, expected: str) -> None:
    """第4列保留解码文本，只有精确斜杠在线；其他文本均为挂错盘而非全表解析错误。"""
    root = StorageRootConfig(
        name="disk", path=Path("/srv/rdp-test/disk"), uuid="11111111-1111-1111-1111-111111111111"
    )
    text = f"20 1 8:1 {raw_root} {root.path} rw - ext4 /dev/alias rw\n"
    assert parse_mountinfo(text)[0].filesystem_root == expected
    result = MountInspector(
        (root,),
        lambda: text,
        lambda _: DeviceNumber(8, 1),
        lambda: datetime(2026, 10, 27, tzinfo=UTC),
    ).inspect()[0]
    assert result.online is (expected == "/")
    assert result.reason is (None if expected == "/" else OfflineReason.SOURCE_MISMATCH)


@pytest.mark.parametrize(
    ("text", "column"),
    [
        ("20 1", "字段数"),
        ("20 1 8:1 / /fake rw shared:1 ext4 /dev/a rw", "分隔符"),
        ("20 1 8:1:2 / /fake rw - ext4 /dev/a rw", "第3列"),
        ("20 1 x:1 / /fake rw - ext4 /dev/a rw", "第3列"),
        ("20 1 8:1 / relative rw - ext4 /dev/a rw", "第5列"),
        (r"20 1 8:1 /bad\777 /fake rw - ext4 /dev/a rw", "第4列"),
        (r"20 1 8:1 / /bad\777 rw - ext4 /dev/a rw", "第5列"),
        (r"20 1 8:1 / /fake rw - ext4 /bad\777 rw", "第9列"),
    ],
)
def test_structural_mountinfo_error_names_column(text: str, column: str) -> None:
    """结构错误报告具体字段位置，不把挂载根、挂载来源错误称为挂载点错误。"""
    with pytest.raises(ValueError, match=column):
        parse_mountinfo(text)


@pytest.mark.parametrize("source", ["", "none", "-"])
def test_opaque_mount_source_does_not_poison_registered_disk(source: str) -> None:
    """文件系统来源文本可为空或占位符，列仍存在时不能使无关的登记盘检查失败。"""
    text = (
        SAMPLE.read_bytes().decode("utf-8")
        + f"9000 44 0:300 / /srv/rdp-test/opaque-source rw future_tag:1 - tmpfs {source} rw\n"
    )
    records = parse_mountinfo(text)
    assert len(records) == 58
    opaque = next(
        record for record in records if record.mount_point == Path("/srv/rdp-test/opaque-source")
    )
    assert opaque.source == source
    root = StorageRootConfig(
        name="dataset1",
        path=Path("/srv/rdp-test/dataset1"),
        uuid="11111111-1111-1111-1111-111111111111",
    )
    result = MountInspector(
        (root,),
        lambda: text,
        lambda _: DeviceNumber(8, 0),
        lambda: datetime(2026, 10, 27, tzinfo=UTC),
    ).inspect()[0]
    assert result.online and result.reason is None
