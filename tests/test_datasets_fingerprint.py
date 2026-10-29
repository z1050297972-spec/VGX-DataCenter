"""L12指纹契约；只操作临时导航，所有哈希期待值独立计算。"""

import os
import shutil
from typing import Any

import pytest
from datasets_support import checkpoint, edit_json, fingerprint
from nav_manifest import FakeNavigation
from pydantic import ValidationError

from rdp.infra.diagnostics import InputError
from rdp.jobs.datasets import catalog
from rdp.jobs.datasets.fingerprint import DatasetFingerprint, fingerprint_dataset


def test_stable(fake_nav: FakeNavigation) -> None:
    """验收2：未改动时两个视图全部入口的指纹相等，不受枚举顺序或mtime改变影响。"""
    first = fingerprint_dataset(
        fake_nav.nav_root, "dataset-14", known_entry_paths=(), checkpoint=checkpoint
    )
    second = fingerprint_dataset(
        fake_nav.nav_root, "dataset-14", known_entry_paths=(), checkpoint=checkpoint
    )
    assert first == second and first.verifiable
    assert {item.path for item in first.entries} == {
        "按任务/libero_10",
        "按格式/lerobot/3.0/libero_10",
    }
    assert all(len(item.json_files) == 4 for item in first.entries)


def test_json_bytes_change(fake_nav: FakeNavigation) -> None:
    """验收2：修改任何一份JSON原字节（包括仅空白）都会改变数据集指纹。"""
    before = fingerprint(fake_nav)
    for name in catalog.REQUIRED_DOCUMENTS:
        path = fake_nav.nav_root / "按任务/libero_10" / name
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        assert fingerprint(fake_nav) != before
        path.write_bytes(original)


def test_member_add_remove(fake_nav: FakeNavigation) -> None:
    """验收2：新增或删除一个直接目录项均改变指纹，隐藏项也包含在清单中。"""
    before = fingerprint(fake_nav)
    path = fake_nav.nav_root / "按任务/libero_10/.extra"
    path.touch()
    assert fingerprint(fake_nav) != before
    path.unlink()
    assert fingerprint(fake_nav) == before


def test_readlink_change(fake_nav: FakeNavigation) -> None:
    """验收2：改变一条实际链接的readlink字面目标改变指纹，断链和相对目标也不跟随。"""
    before = fingerprint(fake_nav)
    path = fake_nav.nav_root / "按任务/libero_10/原始数据"
    path.unlink()
    path.symlink_to("../different-missing")
    after = fingerprint(fake_nav)
    assert after != before
    assert any(
        link.target == "../different-missing" for entry in after.entries for link in entry.links
    )


def test_provenance_presence_hash(fake_nav: FakeNavigation) -> None:
    """L12：来源.json缺失、出现、内容改变、删除均被区分，内容不需要能够解析。"""
    before = fingerprint(fake_nav)
    path = fake_nav.nav_root / "按任务/libero_10/来源.json"
    path.write_text("not JSON")
    added = fingerprint(fake_nav)
    assert added != before and added.verifiable
    path.write_text("different")
    assert fingerprint(fake_nav) != added
    path.unlink()
    assert fingerprint(fake_nav) == before


def test_all_format_entries(fake_nav: FakeNavigation) -> None:
    """L12：增加第二个格式入口、删除或改名已有入口、改JSON身份后仍通过旧路径并集检出变化。"""
    before = fingerprint(fake_nav)
    source = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10"
    added = fake_nav.nav_root / "按格式/lerobot/2.1/libero_10"
    shutil.copytree(source, added, symlinks=True)
    after = fingerprint(fake_nav)
    assert len(after.entries) == 3 and after != before
    known = tuple(item.path for item in after.entries)
    shutil.rmtree(added)
    removed = fingerprint_dataset(
        fake_nav.nav_root, "dataset-14", known_entry_paths=known, checkpoint=checkpoint
    )
    assert removed != after and any(item.state.value == "missing" for item in removed.entries)
    for name in catalog.REQUIRED_DOCUMENTS:
        edit_json(source / name, lambda data: data.update(dataset_id="changed"))
    changed = fingerprint_dataset(
        fake_nav.nav_root, "dataset-14", known_entry_paths=known, checkpoint=checkpoint
    )
    assert changed != removed


def test_additional_json(fake_nav: FakeNavigation) -> None:
    """L12：四个约定文件以外的额外.json也计算原字节摘要，文件不存在与空文件可区分。"""
    before = fingerprint(fake_nav)
    path = fake_nav.nav_root / "按任务/libero_10/extra.json"
    path.write_bytes(b"")
    after = fingerprint(fake_nav)
    assert after != before
    assert any(
        doc.name == "extra.json"
        and doc.sha256 == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        for entry in after.entries
        for doc in entry.json_files
    )


def test_roundtrip_immutable(fake_nav: FakeNavigation) -> None:
    """L12：model_dump_json/model_validate_json往返相等，嵌套字段及元组不可变，编码版本未知拒绝。"""
    value = fingerprint(fake_nav)
    assert DatasetFingerprint.model_validate_json(value.model_dump_json()) == value
    with pytest.raises(ValidationError):
        value.entries[0].path = "changed"
    with pytest.raises(ValidationError):
        DatasetFingerprint.model_validate(value.model_dump() | {"schema_version": 2})


def test_unverifiable(fake_nav: FakeNavigation) -> None:
    """L12：不可读文件、非普通JSON文件或读中变更标记verifiable=False，两个同样失败的值不能授权替换。"""
    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    path.unlink()
    path.symlink_to("absent")
    value = fingerprint(fake_nav)
    assert not value.verifiable
    assert any(
        doc.name == "数据集信息.json" and doc.state.value == "not_regular"
        for entry in value.entries
        if entry.path == "按任务/libero_10"
        for doc in entry.json_files
    )


def test_no_storage_read(fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch) -> None:
    """L12：指纹只观察导航；目标、目录层软链接或JSON软链接不能导致访问假存储根。"""
    original = os.open

    def guarded(path: Any, *args: Any, **kwargs: Any) -> int:
        assert str(path) not in {str(root.path) for root in fake_nav.storage_roots}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    assert fingerprint(fake_nav).verifiable
    monkeypatch.setattr(catalog, "MAX_SCAN_BYTES", 1)
    with pytest.raises(InputError):
        fingerprint(fake_nav)
