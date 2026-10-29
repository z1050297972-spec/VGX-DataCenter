"""读取契约与记录值；使用既有fake_nav在tmp_path展开后逐项变更，不读取真实数据。"""

import json
import os
from typing import Any, cast

import pytest
from datasets_support import LOCATION, checkpoint, document, edit_json, location
from nav_manifest import FakeNavigation

from rdp.infra.diagnostics import ExternalError, InputError
from rdp.jobs.datasets import catalog
from rdp.jobs.datasets.reading import (
    discover_entries,
    extract_recorded_size,
    parse_document,
    read_entry,
)
from rdp.jobs.datasets.types import Link


def test_missing_schema() -> None:
    """验收5：删除schema_version后有效版本为1，原payload仍保留省略状态。"""
    result = document({"dataset_id": "dataset-1"})
    assert result.schema_version == 1
    assert result.payload == {"dataset_id": "dataset-1"}
    assert result.findings == ()


def test_omitted_version(fake_nav: FakeNavigation) -> None:
    """验收5：省略version和显式null投影等价，未知字段不被补写或丢弃。"""
    entry_location = next(
        item
        for item in discover_entries(fake_nav.nav_root).entries
        if item.dataset_name == "libero_10" and item.view.value == "task"
    )
    path = fake_nav.nav_root / entry_location.path / "原始路径.json"
    data: dict[str, Any] = json.loads(path.read_text())
    data["sources"][0].pop("version", None)
    path.write_text(json.dumps(data))
    first = read_entry(fake_nav.nav_root, entry_location, checkpoint=checkpoint)
    data["sources"][0]["version"] = None
    path.write_text(json.dumps(data))
    second = read_entry(fake_nav.nav_root, entry_location, checkpoint=checkpoint)
    assert first.sources[0].version is None
    assert first.sources == second.sources
    assert first.documents[0].payload is not None
    assert "version" not in cast(list[dict[str, Any]], first.documents[0].payload["sources"])[0]


def test_unknown_fields(fake_nav: FakeNavigation) -> None:
    """验收5：顶层和嵌套未知字段在读取、索引保存及读取后完整保留。"""
    loc = location(fake_nav)
    path = fake_nav.nav_root / loc.path / "原始路径.json"
    edit_json(path, lambda data: data.update(extra={"nested": [1, None, "原样"]}))
    result = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    assert result.documents[0].payload is not None
    assert result.documents[0].payload["extra"] == {"nested": [1, None, "原样"]}


def test_invalid_json() -> None:
    """验收5：改坏一份JSON后该文件不可用并有JSON_INVALID五段诊断，其余文件和数据集仍列出。"""
    result = parse_document(LOCATION, "子任务.json", b"{")
    assert result.payload is None
    assert result.findings[0].diagnostic.rule == "JSON_INVALID"
    assert result.findings[0].diagnostic.objects[0].value == "按任务/example"
    assert result.findings[0].diagnostic.consequence


def test_missing_required_field() -> None:
    """验收5：删除依赖字段使整份文件不可用，诊断指明入口、文件、字段、后果和下一步。"""
    result = document({"schema_version": 1})
    assert result.payload is None
    assert result.findings[0].diagnostic.rule == "JSON_REQUIRED_FIELD"
    assert "dataset_id" in result.findings[0].diagnostic.actual


def test_invalid_required_type() -> None:
    """读取契约：依赖字段类型错误、布尔schema_version、非法UTF-8、非对象或非有限JSON数值均不生成假投影。"""
    for data in (
        {"dataset_id": True},
        {"dataset_id": "d", "schema_version": True},
        {"dataset_id": "d", "schema_version": 2},
    ):
        assert document(data).payload is None
    for raw in (
        b"[]",
        b"null",
        b"\xff",
        '{"dataset_id":"d"}'.encode("utf-16"),
        b'{"dataset_id":"d","extra":NaN}',
        b'{"dataset_id":"d","extra":1e999}',
    ):
        assert parse_document(LOCATION, "子任务.json", raw).payload is None

    malformed = {
        "dataset_id": "d",
        "dataset_name": "d",
        "dataset_roots": ["/data"],
        "links": [{"name": "x", "source_path": "relative", "source_type": "directory"}],
        "sources": [],
    }
    assert document(malformed, "原始路径.json").payload is None


def test_unreadable_file(fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收5：注入打开文件失败得到JSON_UNREADABLE，数据集和入口不从列表消失。"""
    original = os.open

    def fail(path: Any, *args: Any, **kwargs: Any) -> int:
        if path == "原始路径.json":
            raise PermissionError("测试权限失败")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", fail)
    result = read_entry(fake_nav.nav_root, location(fake_nav), checkpoint=checkpoint)
    assert result.dataset_id == "dataset-14" and result.documents[0].payload is None
    assert result.documents[1].payload is not None
    assert result.findings[0].diagnostic.rule == "JSON_UNREADABLE"


def test_all_documents_unavailable(fake_nav: FakeNavigation) -> None:
    """验收5：三个文件全不可用仍按位置列出入口，dataset_id为空且不编造永久编号。"""
    loc = location(fake_nav)
    for name in catalog.REQUIRED_DOCUMENTS:
        (fake_nav.nav_root / loc.path / name).write_text("{")
    result = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    assert result.dataset_id is None and result.location.dataset_name == "libero_10"
    assert all(doc.payload is None for doc in result.documents)


def test_derived_fields(fake_nav: FakeNavigation) -> None:
    """读取契约：入口视图格式版本和links/sources.entry_path以位置推导，文件原值保留供核对。"""
    loc = location(fake_nav)
    path = fake_nav.nav_root / loc.path / "原始路径.json"

    def change(data: dict[str, Any]) -> None:
        data["links"][0]["entry_path"] = "旧位置"
        data["sources"][0]["entry_path"] = "旧块位置"

    edit_json(path, change)
    result = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    assert result.links[0].entry_path == "按任务/libero_10/原始数据"
    assert result.sources[0].entry_path == "按任务/libero_10/原始数据"
    assert result.documents[0].payload is not None
    assert (
        cast(list[dict[str, Any]], result.documents[0].payload["links"])[0]["entry_path"]
        == "旧位置"
    )


def test_source_path_boundary() -> None:
    """读取契约：最长完整路径前缀决定source.entry_path，相似前缀不匹配，无链接覆盖保留direct_path。"""
    from rdp.jobs.datasets.reading import derive_source_entry_path

    links = (
        Link("a", "/data", "directory", "按任务/example/a"),
        Link("b", "/data/deep", "directory", "按任务/example/b"),
    )
    assert derive_source_entry_path(LOCATION, "/data/deep/child", links) == "按任务/example/b/child"
    assert derive_source_entry_path(LOCATION, "/database/child", links) == "/database/child"
    with pytest.raises(InputError):
        derive_source_entry_path(LOCATION, "relative", links)


def test_no_target_access(fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收2：将假存储根访问设为抛错，读取导航仍成功；JSON软链接、父目录软链接均不跟随。"""
    loc = location(fake_nav)
    original = os.open

    def guarded(path: Any, *args: Any, **kwargs: Any) -> int:
        assert str(path) not in {str(root.path) for root in fake_nav.storage_roots}
        return original(path, *args, **kwargs)

    monkeypatch.setattr(os, "open", guarded)
    assert read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint).dataset_id == "dataset-14"
    file = fake_nav.nav_root / loc.path / "原始路径.json"
    file.unlink()
    file.symlink_to(fake_nav.storage_roots[0].path / "secret.json")
    assert read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint).documents[0].payload is None
    link = fake_nav.nav_root.parent / "alias"
    link.symlink_to(fake_nav.nav_root, target_is_directory=True)
    with pytest.raises(ExternalError):
        discover_entries(link)


def test_recorded_sizes(fake_nav: FakeNavigation) -> None:
    """验收6：fake_nav的五个样本均取得第4项已知字节数，期望值从原样本独立写定。"""
    expected = {
        "libero_10": 631143389,
        "EgoProDemo": 119642823842,
        "EgoProStandard": 9399163801933,
        "R1_lite_table_withdrawing_mcap": 130810718336,
        "agibot_world_alpha": 8985917978567,
    }
    for entry_location in discover_entries(fake_nav.nav_root).entries:
        result = read_entry(fake_nav.nav_root, entry_location, checkpoint=checkpoint)
        assert result.recorded_size_bytes == expected[entry_location.dataset_name]


def test_missing_recorded_size(fake_nav: FakeNavigation) -> None:
    """验收6：把第4项改为不含全角（N B；的文字时值为None，并出现RECORDED_SIZE_MISSING提示。"""
    loc = location(fake_nav)
    edit_json(
        fake_nav.nav_root / loc.path / "数据集信息.json",
        lambda data: data["fields"][3].update(value_markdown="无记录"),
    )
    result = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    assert result.recorded_size_bytes is None
    assert any(
        item.diagnostic.rule == "RECORDED_SIZE_MISSING" and item.severity.value == "notice"
        for item in result.findings
    )


def test_recorded_size_first_match() -> None:
    """验收6：仅提取第4项第一个匹配，零字节合法，重复项、溢出为None，其余13项保持原文。"""
    data: dict[str, Any] = {
        "dataset_id": "d",
        "fields": [
            {"number": 4, "name": "数据大小", "value_markdown": "零（0 B；说明（99 B；后项"}
        ],
    }
    assert extract_recorded_size(document(data, "数据集信息.json")) == 0
    data["fields"][0]["value_markdown"] = "巨大（9223372036854775808 B；"
    assert extract_recorded_size(document(data, "数据集信息.json")) is None
    data["fields"] *= 2
    assert extract_recorded_size(document(data, "数据集信息.json")) is None


def test_read_budgets(fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch) -> None:
    """读取契约：单文件超32MiB记该文件不可用，整次超128MiB或入口/目录项超限时拒绝发布部分全量。"""
    loc = location(fake_nav)
    monkeypatch.setattr(catalog, "MAX_DOCUMENT_BYTES", 1)
    assert read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint).documents[0].payload is None
    monkeypatch.setattr(catalog, "MAX_ENTRY_MEMBERS", 1)
    with pytest.raises(InputError):
        discover_entries(fake_nav.nav_root)


def test_empty_version_directories(fake_nav: FakeNavigation) -> None:
    """验收2：空lerobot/2.0和2.1不当作数据集；archives映射保留原目录名和中文标点。"""
    catalog = discover_entries(fake_nav.nav_root)
    assert len(catalog.entries) == 10
    assert sum(item.view.value == "task" for item in catalog.entries) == 5
    assert {item.format for item in catalog.entries} == {None, "lerobot", "mcap", "archives"}
    assert all(item.version not in {"2.0", "2.1"} for item in catalog.entries)
