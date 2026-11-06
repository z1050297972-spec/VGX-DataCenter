"""写入规则的契约测试（M1-07：JSON 写出 L10/L11、按格式入口生成 L8/L9、编号分配 L6、来源.json）。

样本取 tests/fixtures/nav 的假导航层（EgoProDemo、agibot_world_alpha），只在 pytest 临时目录里读写，
不碰真实路径。真实导航层副本的对拍由 Claude 在验收 1 里做，不在这里。
"""

import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from nav_manifest import FakeNavigation
from navwrite_support import (
    format_location,
    read_json,
    snapshot,
    task_location,
)

from rdp.infra.diagnostics import InputError
from rdp.jobs.datasets.catalog import MAX_DOCUMENT_BYTES
from rdp.jobs.datasets.reading import derive_source_entry_path
from rdp.jobs.datasets.types import EntryLocation, JsonObject, Link, View
from rdp.jobs.navwrite.allocation import allocate_dataset_id, scan_max_dataset_number
from rdp.jobs.navwrite.jsonio import (
    dump_navigation_json,
    load_navigation_json,
    regenerate_derived_fields,
)
from rdp.jobs.navwrite.provenance import (
    ActorStamp,
    LineageRecord,
    ProvenanceDocument,
    ProvenanceState,
    dump_provenance,
    new_provenance,
    read_provenance,
    with_lineage_record,
)
from rdp.jobs.navwrite.replica import (
    filter_subtasks,
    generate_format_entry,
    select_reachable_sources,
)


def _as_dict(value: object) -> dict[str, Any]:
    """把 JSON 对象当成嵌套字典读（样本结构由测试自己保证）。"""
    return cast(dict[str, Any], value)


JSON_NAMES = ("原始路径.json", "数据集信息.json", "子任务.json")
STAMP = ActorStamp(kind="人工标注", account_id=1, account_name="管理员", at="2026-10-29T10:00:00Z")


def _record(record_id: int) -> LineageRecord:
    """最小的一条血缘记录。"""
    return LineageRecord(
        record_id=record_id,
        kind="转换",
        status="完整",
        note=None,
        inputs=(),
        outputs=(),
        tool=None,
        config=None,
        robot_profile=None,
        parameters=None,
        job_id=None,
        started_at=None,
        finished_at=None,
        ingest_check=None,
        recorded_by=STAMP,
    )


def _location(path: str, view: View, fmt: str | None, version: str | None) -> EntryLocation:
    """构造入口位置。"""
    from pathlib import PurePosixPath

    return EntryLocation(PurePosixPath(path), view, fmt, version, PurePosixPath(path).name)


def test_load_keeps_key_order_and_unknown_keys() -> None:
    """契约 load_navigation_json：键顺序与文件一致，不认识的键原样保留。"""
    content = '{"z": 1, "a": {"y": [1, 2.5], "b": null}, "未知键": "值"}'.encode()
    loaded = load_navigation_json(content)
    assert list(loaded) == ["z", "a", "未知键"]
    assert loaded["a"] == {"y": [1, 2.5], "b": None}
    assert isinstance(loaded["z"], int) and not isinstance(loaded["z"], bool)


@pytest.mark.parametrize(
    "content",
    [
        b"\xff\xfe\x00",  # 非 UTF-8
        b"{not json",
        b"[1, 2]",  # 顶层不是对象
        b'{"a": NaN}',
        b"\xef\xbb\xbf{}",  # BOM 不在约定里
        b"x" * (MAX_DOCUMENT_BYTES + 1),
    ],
)
def test_load_rejects_invalid_documents(content: bytes) -> None:
    """契约 load_navigation_json：非 UTF-8、非 JSON、顶层不是对象、超过 MAX_DOCUMENT_BYTES 都报 InputError，诊断不回显正文。"""
    with pytest.raises(InputError) as caught:
        load_navigation_json(content)
    rendered = repr(caught.value.diagnostics)
    assert "not json" not in rendered and "xxxx" not in rendered


def test_dump_format_l11() -> None:
    """L11：dump_navigation_json 写 2 空格缩进、ensure_ascii=False、结尾恰好一个换行；新键追加在末尾。"""
    payload: JsonObject = {"b": 1, "a": ["中文", {"c": None}], "空": {}, "list": []}
    payload["新键"] = True
    dumped = dump_navigation_json(payload)
    assert dumped.endswith(b"}\n") and not dumped.endswith(b"\n\n")
    text = dumped.decode("utf-8")
    assert "中文" in text and "\\u" not in text
    assert text.startswith('{\n  "b": 1,\n  "a": [\n    "中文"')
    assert list(json.loads(text)) == ["b", "a", "空", "list", "新键"]
    with pytest.raises(InputError):
        dump_navigation_json({"x": float("nan")})


def test_roundtrip_is_byte_identical_except_derived(fake_nav: FakeNavigation) -> None:
    """L11 验收：对假导航层每份 JSON，load 再 dump 与原字节相同，只允许 L10 推导字段带来的差异。"""
    checked = 0
    for path in sorted(fake_nav.nav_root.rglob("*.json")):
        original = path.read_bytes()
        assert dump_navigation_json(load_navigation_json(original)) == original, path
        checked += 1
    assert checked == 30


def test_regenerate_derived_fields_writes_version_null() -> None:
    """L10：按格式入口省略 version 时，regenerate_derived_fields 显式写出 version: null，键已存在则留在原位。"""
    location = _location("按格式/mcap/X", View.FORMAT, "mcap", None)
    payload: JsonObject = {
        "dataset_id": "dataset-1",
        "view": "format",
        "format": "mcap",
        "links": [],
        "sources": [],
    }
    result = regenerate_derived_fields(payload, location)
    assert result["version"] is None and list(result)[-1] == "version"
    keep: JsonObject = {
        "version": "9",
        "view": "x",
        "dataset_id": "dataset-1",
        "links": [],
        "sources": [],
    }
    again = regenerate_derived_fields(keep, _location("按任务/X", View.TASK, None, None))
    assert list(again)[:3] == ["version", "view", "dataset_id"]
    assert again["version"] is None and again["view"] == "task" and again["format"] is None
    assert keep["version"] == "9"  # 输入不被改动


def test_regenerate_derived_fields_does_not_add_schema_version() -> None:
    """L10：数据集信息.json 不补 schema_version；原始路径.json 缺 schema_version 时同样不补。"""
    location = _location("按任务/X", View.TASK, None, None)
    result = regenerate_derived_fields(
        {"dataset_id": "dataset-1", "links": [], "sources": []}, location
    )
    assert "schema_version" not in result
    info: JsonObject = {"dataset_id": "dataset-1", "fields": []}
    assert "schema_version" not in regenerate_derived_fields(info, location)
    assert "links" not in regenerate_derived_fields(info, location)


def test_regenerate_rederives_entry_paths(fake_nav: FakeNavigation) -> None:
    """L8：regenerate_derived_fields 重新推导 links[].entry_path 和 sources[].entry_path，与 reading.derive_source_entry_path 一致。"""
    nav = fake_nav.nav_root
    location = format_location(nav, "agibot_world_alpha")
    payload = copy.deepcopy(read_json(nav, location, "原始路径.json"))
    for link in _as_dict(payload)["links"]:
        link["entry_path"] = "错的"
    for source in _as_dict(payload)["sources"]:
        source["entry_path"] = "错的"
    result = _as_dict(regenerate_derived_fields(payload, location))
    links = tuple(
        Link(item["name"], item["source_path"], item["source_type"], item["entry_path"])
        for item in result["links"]
    )
    assert all(link.entry_path == f"{location.path}/{link.name}" for link in links)
    for source in result["sources"]:
        assert source["entry_path"] == derive_source_entry_path(
            location, source["direct_path"], links
        )
    assert any(s["entry_path"].startswith(str(location.path)) for s in result["sources"])
    assert any(s["entry_path"].startswith("/") for s in result["sources"])
    with pytest.raises(InputError):
        regenerate_derived_fields({"links": "不是数组", "sources": []}, location)


def test_select_reachable_sources_boundary() -> None:
    """L8：direct_path 等于链接目标或位于其下（紧跟 /）才算够得着；/a/b 不覆盖 /a/bc。"""
    sources: tuple[JsonObject, ...] = tuple(
        {"source_id": f"s{i}", "direct_path": path}
        for i, path in enumerate(["/a/b", "/a/b/c", "/a/bc", "/a/b/", "/x"])
    )
    reached, unreached = select_reachable_sources(sources, ("/a/b",))
    assert [s["source_id"] for s in reached] == ["s0", "s1", "s3"]
    assert [s["source_id"] for s in unreached] == ["s2", "s4"]
    with pytest.raises(InputError):
        select_reachable_sources(({"source_id": "s"},), ("/a",))
    with pytest.raises(InputError):
        select_reachable_sources(sources, ("相对路径",))


def test_select_reachable_sources_keeps_order_and_partitions() -> None:
    """L8、L9：两组各自保持输入顺序，不重叠，合起来等于输入。"""
    sources: tuple[JsonObject, ...] = tuple(
        {"source_id": f"s{i}", "direct_path": f"/r{i % 3}/d{i}"} for i in range(9)
    )
    reached, unreached = select_reachable_sources(sources, ("/r2", "/r0"))
    ids = [s["source_id"] for s in reached]
    assert ids == sorted(ids, key=lambda value: int(str(value)[1:]))
    assert {id(s) for s in reached}.isdisjoint({id(s) for s in unreached})
    assert sorted([*reached, *unreached], key=lambda s: int(str(s["source_id"])[1:])) == list(
        sources
    )
    assert len(reached) == 6 and len(unreached) == 3
    assert select_reachable_sources(sources, ()) == ((), sources)


def _subtasks() -> JsonObject:
    """两个任务的 子任务.json：t1 引用 a、b，t2 只引用 c，t3 的引用没有 source_id。"""
    return {
        "dataset_id": "dataset-1",
        "task_count": 3,
        "未知": {"x": 1},
        "tasks": [
            {"task_key": "t1", "sources": [{"source_id": "a"}, {"source_id": "b"}], "额外": 1},
            {"task_key": "t2", "sources": [{"source_id": "c"}]},
            {"task_key": "t3", "sources": [{"root": "/没有编号"}]},
        ],
        "shared_source_roots": [{"source_id": "c", "root": "/c", "task_keys": ["t2"]}],
    }


def test_filter_subtasks_drops_unreferenced_tasks() -> None:
    """L8：filter_subtasks 只保留引用到入选数据块的任务，任务内部 sources[] 同样筛，task_count 重算，未知键保留。"""
    original = _subtasks()
    snapshot_before = copy.deepcopy(original)
    raw, omitted, dropped = filter_subtasks(original, frozenset({"a"}))
    result = _as_dict(raw)
    assert original == snapshot_before
    assert [t["task_key"] for t in result["tasks"]] == ["t1", "t3"]
    assert result["tasks"][0]["sources"] == [{"source_id": "a"}]
    assert result["tasks"][0]["额外"] == 1
    assert result["task_count"] == 2 and result["未知"] == {"x": 1}
    assert result["shared_source_roots"] == original["shared_source_roots"]
    assert list(result) == list(original)
    assert (omitted, dropped) == (2, ("t2",))
    with pytest.raises(InputError):
        filter_subtasks({"tasks": {"不是": "数组"}}, frozenset())


def test_filter_subtasks_reports_counts() -> None:
    """L8：返回被筛掉的引用条数和整体去掉的 task_key；入选集合为空时所有任务都去掉。"""
    raw, omitted, dropped = filter_subtasks(_subtasks(), frozenset())
    result = _as_dict(raw)
    # 没有 source_id 的引用判断不了，保留，所以 t3 仍在；其余两个任务整体去掉。
    assert [t["task_key"] for t in result["tasks"]] == ["t3"]
    assert omitted == 3 and dropped == ("t1", "t2")
    full, omitted_none, dropped_none = filter_subtasks(_subtasks(), frozenset({"a", "b", "c"}))
    assert (omitted_none, dropped_none) == (0, ()) and full["task_count"] == 3


def test_generate_egopro_demo_format_entry(fake_nav: FakeNavigation) -> None:
    """L8 样本一：EgoProDemo 的 lerobot/3.0 入口只链接 EgoProStandard-body/lerobot，生成的 sources[] 只含该目录下的数据块，子任务数与规范副本筛选结果一致。"""
    nav = fake_nav.nav_root
    canonical = snapshot(nav, task_location(nav, "EgoProDemo"))
    current = snapshot(nav, format_location(nav, "EgoProDemo"))
    result = generate_format_entry(canonical, current)
    assert [f.name for f in result.files] == list(JSON_NAMES)
    manifest = _as_dict(load_navigation_json(result.files[0].content))
    target = current.links[0].source_path
    assert target.endswith("EgoProStandard-body/lerobot")
    assert [s["source_id"] for s in manifest["sources"]] == [s.source_id for s in canonical.sources]
    assert all(str(s["direct_path"]).startswith(target + "/") for s in manifest["sources"])
    assert all(
        str(s["entry_path"]).startswith("按格式/lerobot/3.0/EgoProDemo/原始数据/")
        for s in manifest["sources"]
    )
    assert manifest["view"] == "format" and manifest["format"] == "lerobot"
    assert (
        manifest["version"] == "3.0"
        and manifest["links"] == read_json(nav, current.location, "原始路径.json")["links"]
    )
    assert manifest["dataset_id"] == canonical.dataset_id
    assert result.omitted_source_ids == () and result.dropped_task_keys == ()
    subtasks = _as_dict(load_navigation_json(result.files[2].content))
    assert subtasks["task_count"] == len(subtasks["tasks"]) == 2
    assert subtasks["view"] == "format"
    # 文件里本来就是这样：生成结果与样本里现成的按格式入口逐字节相同。
    for generated in result.files:
        assert generated.content == (nav / current.location.path / generated.name).read_bytes()


def test_generate_alpha_omits_unreachable_blocks(fake_nav: FakeNavigation) -> None:
    """L9 样本二：agibot_world_alpha 的按格式入口生成后少 3 个链接够不着的数据块，omitted_source_ids 恰好列出它们，规范副本里它们的 entry_path 仍是绝对路径。"""
    nav = fake_nav.nav_root
    canonical = snapshot(nav, task_location(nav, "agibot_world_alpha"))
    current = snapshot(nav, format_location(nav, "agibot_world_alpha"))
    result = generate_format_entry(canonical, current)
    manifest = _as_dict(load_navigation_json(result.files[0].content))
    assert [s["source_id"] for s in manifest["sources"]] == ["src_73acac5cbe70"]
    assert result.omitted_source_ids == ("src_0ce579c7bddf", "src_2a2c94e25231", "src_489eb4dc26b6")
    omitted_in_canonical = [
        s for s in canonical.sources if s.source_id in result.omitted_source_ids
    ]
    assert len(omitted_in_canonical) == 3
    assert all(
        s.entry_path == s.direct_path and s.entry_path.startswith("/") for s in omitted_in_canonical
    )
    assert (
        manifest["task_metadata"]
        == read_json(nav, canonical.location, "原始路径.json")["task_metadata"]
    )


def test_generate_copies_dataset_info_verbatim(fake_nav: FakeNavigation) -> None:
    """L8：数据集信息.json 整份复制，生成的字节与规范副本相同。"""
    nav = fake_nav.nav_root
    canonical = snapshot(nav, task_location(nav, "EgoProDemo"))
    current = snapshot(nav, format_location(nav, "EgoProDemo"))
    result = generate_format_entry(canonical, current)
    expected = (nav / canonical.location.path / "数据集信息.json").read_bytes()
    assert result.files[1].name == "数据集信息.json" and result.files[1].content == expected


def test_generate_uses_current_entry_links(fake_nav: FakeNavigation) -> None:
    """L8：链接以该按格式入口自己的 links[] 为准，不用规范副本的链接。"""
    nav = fake_nav.nav_root
    canonical = snapshot(nav, task_location(nav, "agibot_world_alpha"))
    location = format_location(nav, "agibot_world_alpha")
    path = nav / location.path / "原始路径.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["links"] = [lk for lk in payload["links"] if lk["name"] != "observations"]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    result = generate_format_entry(canonical, snapshot(nav, location))
    manifest = _as_dict(load_navigation_json(result.files[0].content))
    assert [lk["name"] for lk in manifest["links"]] == ["parameters", "proprio_stats", "task_info"]
    assert manifest["sources"] == []
    assert len(result.omitted_source_ids) == 4


def test_generate_rejects_wrong_dataset_or_view(fake_nav: FakeNavigation) -> None:
    """契约 generate_format_entry：canonical 与 current 的 dataset_id 不同、current 不是按格式入口时报 InputError。"""
    nav = fake_nav.nav_root
    canonical = snapshot(nav, task_location(nav, "EgoProDemo"))
    other = snapshot(nav, format_location(nav, "agibot_world_alpha"))
    with pytest.raises(InputError):
        generate_format_entry(canonical, other)
    with pytest.raises(InputError):
        generate_format_entry(canonical, canonical)
    (nav / canonical.location.path / "子任务.json").write_text("{坏", encoding="utf-8")
    with pytest.raises(InputError):
        generate_format_entry(
            snapshot(nav, canonical.location), snapshot(nav, format_location(nav, "EgoProDemo"))
        )


def _make_entry(nav_root: Path, view: str, name: str, dataset_id: str | None) -> None:
    """造一个最小入口；dataset_id 为 None 时三份 JSON 都写成坏的。"""
    directory = nav_root / view / name
    directory.mkdir(parents=True)
    for file in JSON_NAMES:
        content = (
            "{坏"
            if dataset_id is None
            else json.dumps({"dataset_id": dataset_id, "schema_version": 1})
        )
        (directory / file).write_text(content, encoding="utf-8")


def test_allocate_dataset_id_scans_removed(tmp_path: Path) -> None:
    """L6 验收：已移除/ 下有 dataset-40_x/ 时，分配到 dataset-41。"""
    _make_entry(tmp_path, "按任务", "a", "dataset-12")
    (tmp_path / "已移除" / "dataset-40_x").mkdir(parents=True)
    assert scan_max_dataset_number(tmp_path) == 40
    assert allocate_dataset_id(tmp_path) == "dataset-41"
    assert list(tmp_path.iterdir()).count(tmp_path / "已分配编号.json") == 0  # 不记账本


def test_allocate_dataset_id_takes_max_not_count(tmp_path: Path) -> None:
    """L6：按任务/ 里编号有空洞时取最大加 1，不取个数加 1。"""
    for name, number in (("a", "dataset-03"), ("b", "dataset-17"), ("c", "dataset-5")):
        _make_entry(tmp_path, "按任务", name, number)
    assert allocate_dataset_id(tmp_path) == "dataset-18"


def test_allocate_dataset_id_min_two_digits(tmp_path: Path) -> None:
    """L6：没有任何数据集时分配 dataset-01，至少两位。"""
    assert allocate_dataset_id(tmp_path) == "dataset-01"
    (tmp_path / "按任务").mkdir()
    (tmp_path / "已移除").mkdir()
    assert scan_max_dataset_number(tmp_path) == 0
    _make_entry(tmp_path, "按任务", "a", "dataset-8")
    assert allocate_dataset_id(tmp_path) == "dataset-09"
    _make_entry(tmp_path, "按任务", "b", "dataset-99")
    assert allocate_dataset_id(tmp_path) == "dataset-100"


def test_allocate_dataset_id_refuses_unreadable_entry(tmp_path: Path) -> None:
    """契约 scan_max_dataset_number：有入口读不出 dataset_id 时报 InputError，不分配可能重复的编号。"""
    _make_entry(tmp_path, "按任务", "a", "dataset-12")
    _make_entry(tmp_path, "按任务", "坏", None)
    with pytest.raises(InputError):
        scan_max_dataset_number(tmp_path)
    with pytest.raises(InputError):
        allocate_dataset_id(tmp_path)


def test_allocate_dataset_id_refuses_unnumbered_removed_dir(tmp_path: Path) -> None:
    """契约 scan_max_dataset_number：已移除/ 下有不带编号前缀的目录名时报 InputError。"""
    (tmp_path / "已移除" / "没有编号").mkdir(parents=True)
    with pytest.raises(InputError):
        scan_max_dataset_number(tmp_path)


def _write_provenance(directory: Path, content: str | bytes) -> None:
    """在入口目录里写来源.json。"""
    directory.mkdir(parents=True, exist_ok=True)
    data = content.encode() if isinstance(content, str) else content
    (directory / "来源.json").write_bytes(data)


def test_read_provenance_absent(tmp_path: Path) -> None:
    """契约 read_provenance：文件不存在为 ABSENT，不当作错误。"""
    result = read_provenance(tmp_path)
    assert result.state is ProvenanceState.ABSENT
    assert result.document is None and result.sha256 is None and result.reason is None


def test_read_provenance_invalid_never_becomes_empty(tmp_path: Path) -> None:
    """契约 read_provenance：软链接、非普通文件、坏 JSON、未知 schema_version 为 INVALID 且给出原因，不替换成空文档。"""
    base: dict[str, Any] = {
        "schema_version": 1,
        "dataset_id": "dataset-1",
        "dataset_name": "x",
        "data_origin": "未知",
        "data_origin_set_by": None,
        "collection_task_id": None,
        "lineage": [],
    }
    cases: dict[str, str | None] = {
        "bad": "{坏",
        "future": json.dumps(base | {"schema_version": 3}),
        "extra": json.dumps(base | {"多余": 1}),
        "huge": " " * (MAX_DOCUMENT_BYTES + 1),
    }
    for name, content in cases.items():
        directory = tmp_path / name
        assert content is not None
        _write_provenance(directory, content)
        result = read_provenance(directory)
        assert result.state is ProvenanceState.INVALID, name
        assert result.document is None and result.reason, name
    link_dir = tmp_path / "link"
    link_dir.mkdir()
    target = tmp_path / "target.json"
    target.write_text(json.dumps(base), encoding="utf-8")
    (link_dir / "来源.json").symlink_to(target)
    assert read_provenance(link_dir).state is ProvenanceState.INVALID
    dir_dir = tmp_path / "isdir"
    (dir_dir / "来源.json").mkdir(parents=True)
    assert read_provenance(dir_dir).state is ProvenanceState.INVALID


DRAFT = Path(__file__).parent / "fixtures" / "provenance-draft.json"


def test_read_provenance_valid_draft_sample(tmp_path: Path) -> None:
    """来源.json 第 1 版：15 号票草样去掉 _example_platform_record 后可读，lineage 一条，字段对得上。"""
    _write_provenance(tmp_path, DRAFT.read_text(encoding="utf-8"))
    result = read_provenance(tmp_path)
    assert result.state is ProvenanceState.VALID and result.reason is None
    document = result.document
    assert document is not None and result.sha256 is not None
    assert (document.dataset_id, document.dataset_name) == (
        "dataset-29",
        "R1_lite_table_withdrawing_lerobot",
    )
    assert document.schema_version == 2 and document.collection_task_id is None
    assert "data_origin" not in dump_provenance(document)
    assert len(document.lineage) == 1 and document.lineage[0].status == "来历部分未知"
    assert document.lineage[0].inputs[0] == {
        "dataset_id": "dataset-35",
        "source_id": "src_01e0bc7e9cc8",
    }
    # collection_task_id 用文本或 null（9 点决定第 9 条）
    text = DRAFT.read_text(encoding="utf-8").replace(
        '"collection_task_id": null', '"collection_task_id": "task-7"'
    )
    _write_provenance(tmp_path, text)
    loaded = read_provenance(tmp_path).document
    assert loaded is not None and loaded.collection_task_id == "task-7"


def test_new_provenance_has_empty_lineage() -> None:
    """契约 new_provenance：第 2 版只存身份、采集任务和血缘，空血缘表示来历未知。"""
    created = new_provenance("dataset-36", "新数据集")
    assert created.schema_version == 2
    assert created.lineage == () and created.collection_task_id is None


def _doc() -> ProvenanceDocument:
    """带一条血缘的文档。"""
    return new_provenance("dataset-36", "n").model_copy(update={"lineage": (_record(1),)})


def test_with_lineage_record_is_append_only() -> None:
    """契约 with_lineage_record：只在末尾追加，已有记录一条不改；record_id 不是下一个编号时报 InputError。"""
    document = new_provenance("dataset-36", "n")
    first = with_lineage_record(document, _record(1))
    second = with_lineage_record(first, _record(2))
    assert second.lineage[0] is first.lineage[0] and [r.record_id for r in second.lineage] == [1, 2]
    assert document.lineage == ()
    for wrong in (1, 2, 4):
        with pytest.raises(InputError):
            with_lineage_record(second, _record(wrong))
    with pytest.raises(InputError):
        with_lineage_record(document, _record(2))


def test_dump_provenance_key_order() -> None:
    """契约 dump_provenance：第 2 版只写五个字段，空值写 null，血缘结构保持原样。"""
    dumped = dump_provenance(new_provenance("dataset-36", "n"))
    assert list(dumped) == [
        "schema_version",
        "dataset_id",
        "dataset_name",
        "collection_task_id",
        "lineage",
    ]
    assert dumped["schema_version"] == 2 and dumped["collection_task_id"] is None
    assert dumped["lineage"] == []
    full = dump_provenance(_doc())
    lineage: list[dict[str, Any]] = _as_dict(full)["lineage"]
    assert list(lineage[0])[:3] == ["record_id", "kind", "status"]
    assert load_navigation_json(dump_navigation_json(full)) == full


def test_entry_snapshot_reports_provenance_three_states(fake_nav: FakeNavigation) -> None:
    """EntrySnapshot 的来源.json 三态字段：不存在、可读、无法读取，provenance_present 的含义不变。"""
    from rdp.jobs.datasets.types import ProvenanceState

    nav = fake_nav.nav_root
    location = task_location(nav, "EgoProDemo")
    entry = nav / location.path
    absent = snapshot(nav, location)
    assert absent.provenance_state is ProvenanceState.ABSENT and absent.provenance_present is False
    _write_provenance(entry, DRAFT.read_text(encoding="utf-8"))
    valid = snapshot(nav, location)
    assert valid.provenance_state is ProvenanceState.VALID and valid.provenance_present is True
    _write_provenance(entry, "{坏")
    invalid = snapshot(nav, location)
    assert (
        invalid.provenance_state is ProvenanceState.INVALID and invalid.provenance_present is True
    )
    (entry / "来源.json").unlink()
    (entry / "来源.json").symlink_to(entry / "原始路径.json")
    linked = snapshot(nav, location)
    assert linked.provenance_state is ProvenanceState.INVALID and linked.provenance_present is True
