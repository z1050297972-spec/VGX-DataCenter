"""假导航层契约清单（10、验收5/6/7），不以规划目录或真实数据盘为输入。"""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, cast

import pytest
from nav_manifest import FakeNavigation, NavManifest, expand_fake_nav

FIXTURES = Path(__file__).parent / "fixtures" / "nav"
DATASETS = {
    "libero_10",
    "R1_lite_table_withdrawing_mcap",
    "EgoProStandard",
    "EgoProDemo",
    "agibot_world_alpha",
}


def _json(path: Path) -> dict[str, Any]:
    """只读临时展开或仓库样本的JSON对象。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _inject(monkeypatch: pytest.MonkeyPatch, overrides: dict[Path, str]) -> None:
    """在文件读取边界注入坏样本，仓库原件始终不改写。"""
    original = Path.read_text

    def read(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        return (
            overrides[path]
            if path in overrides
            else original(path, encoding=encoding, errors=errors)
        )

    monkeypatch.setattr(Path, "read_text", read)


def test_two_views_five_entries(fake_nav: FakeNavigation) -> None:
    """验收5：两个视图各有指定五个入口且各有三份JSON，保持dataset_id配对、规范副本和格式差异。"""
    for view in ("按任务", "按格式"):
        entries = [
            entry for entry in fake_nav.manifest.entries if entry.path.startswith(view + "/")
        ]
        assert len(entries) == 5 and {Path(entry.path).name for entry in entries} == DATASETS
        for entry in entries:
            directory = fake_nav.nav_root / entry.path
            originals = _json(directory / "原始路径.json")
            for name in ("原始路径.json", "数据集信息.json", "子任务.json"):
                assert _json(directory / name)["dataset_id"] == entry.dataset_id
            assert originals["view"] == ("task" if view == "按任务" else "format")


def test_links_inside_fake_roots(fake_nav: FakeNavigation) -> None:
    """验收5：十八条真实软链接全部可解析且目标位于返回的假根内，不是复制目录或文本链接。"""
    count = 0
    for entry in fake_nav.manifest.entries:
        for link in entry.links:
            path = fake_nav.nav_root / entry.path / link.name
            assert path.is_symlink()
            resolved = path.resolve(strict=True)
            assert any(resolved.is_relative_to(root.path) for root in fake_nav.storage_roots)
            assert path.readlink().is_absolute()
            count += 1
    assert count == 18


def test_cross_disk_and_alpha_links(fake_nav: FakeNavigation) -> None:
    """验证EgoProStandard两个跨盘链接和alpha四个子目录链接，两视图目标严格对应采集布局。"""
    roots = {root.name: root.path for root in fake_nav.storage_roots}
    for name in ("dataset1", "dataset2"):
        task = fake_nav.nav_root / "按任务/EgoProStandard" / ("原始数据__" + name)
        formatted = fake_nav.nav_root / "按格式/mcap/EgoProStandard" / ("原始数据__" + name)
        assert task.resolve() == roots[name] / "EgoProStandard"
        assert formatted.resolve() == roots[name] / "EgoProStandard/mcap"
    for base in ("按任务/agibot_world_alpha", "按格式/tar、tar.gz（含分卷）/agibot_world_alpha"):
        for name in ("observations", "parameters", "proprio_stats", "task_info"):
            assert (fake_nav.nav_root / base / name).resolve() == roots[
                "dataset2"
            ] / "agibot_world_alpha" / name


def test_empty_format_directories(fake_nav: FakeNavigation) -> None:
    """验收5：lerobot/2.0和2.1存在且为空；格式目录保留中文标点。"""
    for version in ("2.0", "2.1"):
        directory = fake_nav.nav_root / "按格式/lerobot" / version
        assert directory.is_dir() and list(directory.iterdir()) == []
    assert (fake_nav.nav_root / "按格式/tar、tar.gz（含分卷）").is_dir()


def test_non_dataset_layout(fake_nav: FakeNavigation) -> None:
    """验收5：索引、文档、工具、解压样本、VGX_video及采集到的第一层名字均存在，文档仅为极小占位。"""
    expected: dict[str, set[str]] = {
        "索引": set(),
        "文档": {
            "AgiBotWorld2026_官方格式核对.md",
            "AgiBotWorld2026_免解压查看指南.md",
            "LeRobot格式数据占比统计.md",
        },
        "工具": {"mcap2lerobot"},
        "解压样本": {
            "agibot_world_2026_simulation_scoop_popcorn_lite",
            "agitbot_world_2026_richinteraction_4439_458713",
        },
        "VGX_video": {"photo_particles_edit", "photo_particles_fullframe"},
    }
    for name, children in expected.items():
        directory = fake_nav.nav_root / name
        assert directory.is_dir()
        assert {path.name for path in directory.iterdir()} == children
    assert all(path.stat().st_size <= 1024 for path in (fake_nav.nav_root / "文档").iterdir())


def test_placeholder_expansion(fake_nav: FakeNavigation) -> None:
    """验收5：展开JSON键、值和Markdown内无已知根占位符或真实挂载前缀；保留LeRobot的video_key/chunk_index模板。"""
    for root in (fake_nav.nav_root, *(item.path for item in fake_nav.storage_roots)):
        for path in root.rglob("*.json"):
            content = path.read_text(encoding="utf-8")
            assert all(token not in content for token in ("{dataset1}", "{dataset2}", "{nav_root}"))
            assert "/" + "mnt/" not in content
    info = _json(fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json")
    assert "{chunk_index:03d}" in info["data_path"] and "{video_key}" in info["video_path"]


def test_prefix_boundaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证路径按完整分量替换，dataset1和datasets前缀不串位，相似前缀名字不误替换。"""
    source = FIXTURES / "samples/nav/按任务/libero_10/数据集信息.json"
    data = _json(source)
    data["probe"] = {
        "{dataset1}/key": "`{nav_root}/按任务/libero_10`，{dataset2}/x；dataset10/name"
    }
    _inject(monkeypatch, {source: json.dumps(data, ensure_ascii=False)})
    nav = expand_fake_nav(tmp_path, fixture_dir=FIXTURES)
    result = _json(nav.nav_root / "按任务/libero_10/数据集信息.json")["probe"]
    assert result == {
        str(
            nav.storage_roots[0].path / "key"
        ): f"`{nav.nav_root}/按任务/libero_10`，{nav.storage_roots[1].path}/x；dataset10/name"
    }


def test_real_meta_fields(fake_nav: FakeNavigation) -> None:
    """验证libero的franka、20、v3.0及EgoProDemo的null、30.0、v3.0原样保留，可经假根直接读取。"""
    libero = _json(fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json")
    ego = _json(
        fake_nav.storage_roots[1].path
        / "EgoProDemo/EgoProStandard-body/lerobot/Adjust Shelf Labels/5800ed0b-0fd7-438d-89a8-ef23de66723d/meta/info.json"
    )
    assert (libero["robot_type"], libero["fps"], libero["codebase_version"]) == (
        "franka",
        20,
        "v3.0",
    )
    assert (ego["robot_type"], ego["fps"], ego["codebase_version"]) == (None, 30.0, "v3.0")


def test_consistent_truncation(fake_nav: FakeNavigation) -> None:
    """验证两个视图和三份JSON保留相同source_id/task_key选择，关联元数据与计数同步，历史失效引用单独声明。"""
    for selection in fake_nav.manifest.selections:
        entries = [
            entry for entry in fake_nav.manifest.entries if entry.dataset_id == selection.dataset_id
        ]
        assert len(entries) == 2
        information: list[dict[str, Any]] = []
        for entry in entries:
            directory = fake_nav.nav_root / entry.path
            paths, tasks = _json(directory / "原始路径.json"), _json(directory / "子任务.json")
            assert tuple(item["source_id"] for item in paths["sources"]) == selection.source_ids
            assert tuple(item["task_key"] for item in tasks["tasks"]) == selection.task_keys
            assert tasks["task_count"] == len(tasks["tasks"])
            assert all(
                source["source_id"] in selection.source_ids
                for task in tasks["tasks"]
                for source in task["sources"]
            )
            assert all(
                item["task_key"] in selection.task_keys for item in paths.get("task_metadata", [])
            )
            assert all(
                key in selection.task_keys
                for item in tasks.get("shared_source_roots", [])
                for key in item["task_keys"]
            )
            information.append(_json(directory / "数据集信息.json"))
        assert information[0] == information[1]
    assert [len(item.source_ids) for item in fake_nav.manifest.selections] == [1, 3, 4, 2, 4]


def test_difficult_characters(fake_nav: FakeNavigation) -> None:
    """验证中文标点、空格、括号、撇号在样本路径及链接中保留，JSON解析与路径访问均成功。"""
    root = fake_nav.storage_roots[1].path / "EgoProStandard/mcap"
    for name in (
        "Affix Shipping Label (on Package Surface)",
        "Secure the biscuit tin's latch lid_plum",
    ):
        assert (root / name).is_dir()
        assert (
            fake_nav.nav_root / "按格式/mcap/EgoProStandard/原始数据__dataset2" / name
        ).resolve() == root / name
    text = (fake_nav.nav_root / "按任务/EgoProStandard/原始路径.json").read_text(encoding="utf-8")
    assert "tin's" in text and "(on Package Surface)" in text
    assert (
        fake_nav.nav_root / "按格式/tar、tar.gz（含分卷）/agibot_world_alpha/observations"
    ).is_symlink()


def test_provenance(fake_nav: FakeNavigation) -> None:
    """验收6：32份记录各有原件相对路径、来源分量、sha256、字节数和具体截短理由；运行测试不打开来源原件。"""
    samples = fake_nav.manifest.samples
    assert len(samples) == 32 and len({item.asset_path for item in samples}) == 32
    for item in samples:
        assert item.source_path_parts[0] == "mnt"
        assert len(item.original_sha256) == 64 and int(item.original_sha256, 16) >= 0
        assert item.original_size_bytes > 0 and item.truncation
        assert (FIXTURES / item.sample_file).is_file()
    known = next(
        item for item in samples if item.asset_path == "nav/按任务/EgoProStandard/原始路径.json"
    )
    assert (
        known.original_sha256 == "cd271c60c4e3083f80cb92815dcd3c0759d77e4c09c69a0b03f1f5b00a021b07"
    )
    assert known.original_size_bytes == 337389 and "734" in known.truncation
    assert known.source_path_parts == (
        "mnt",
        "datasets",
        "按任务",
        "EgoProStandard",
        "原始路径.json",
    )


def test_manifest_schema() -> None:
    """验证清单与NavManifest和manifest.schema.json一致；版本、数量、身份重复缺失、来源记录和字节限制错误拒绝。"""
    original = _json(FIXTURES / "manifest.json")
    assert NavManifest.model_json_schema() == _json(FIXTURES / "manifest.schema.json")
    assert NavManifest.model_validate(original).schema_version == 1
    mutations: list[dict[str, Any]] = []
    for field in ("roots", "entries", "samples", "selections"):
        data = deepcopy(original)
        data[field].pop()
        mutations.append(data)
        data = deepcopy(original)
        data[field][-1] = data[field][0]
        mutations.append(data)
    for key, value in (
        ("source_path_parts", list[str]()),
        ("original_sha256", "bad"),
        ("truncation", ""),
    ):
        data = deepcopy(original)
        data["samples"][0][key] = value
        mutations.append(data)
    data = deepcopy(original)
    data["schema_version"] = 2
    mutations.append(data)
    data = deepcopy(original)
    data["files"][0]["text"] = "中" * 1025
    mutations.append(data)
    for data in mutations:
        with pytest.raises(ValueError):
            NavManifest.model_validate(data)


def test_escape_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证未知占位符、绝对目标、..、NUL、夹具软链接逃逸、路径冲突在写入前拒绝，tmp_path之外无改动。"""
    original = _json(FIXTURES / "manifest.json")
    for index, destination in enumerate(
        (
            "{unknown}/x",
            str(tmp_path / "escaped"),
            "{dataset1}/../escaped",
            "{dataset1}/bad\x00",
            original["samples"][0]["destination"],
        )
    ):
        data = deepcopy(original)
        data["files"][0]["destination"] = destination
        target = tmp_path / str(index)
        target.mkdir()
        with monkeypatch.context() as patch:
            _inject(patch, {FIXTURES / "manifest.json": json.dumps(data)})
            with pytest.raises(ValueError):
                expand_fake_nav(target, fixture_dir=FIXTURES)
        assert list(target.iterdir()) == []
    assert not (tmp_path / "escaped").exists()


def test_isolated_expansion(tmp_path: Path) -> None:
    """验证两次展开目录互不共享，修改一个不会影响另一个或仓库样本，返回根配置可直接注入平台。"""
    left, right = tmp_path / "left", tmp_path / "right"
    left.mkdir()
    right.mkdir()
    source = FIXTURES / "samples/nav/按任务/libero_10/原始路径.json"
    original = source.read_bytes()
    first = expand_fake_nav(left, fixture_dir=FIXTURES)
    second = expand_fake_nav(right, fixture_dir=FIXTURES)
    (first.nav_root / "按任务/libero_10/原始路径.json").write_text("{}", encoding="utf-8")
    assert _json(second.nav_root / "按任务/libero_10/原始路径.json")["dataset_id"] == "dataset-14"
    assert source.read_bytes() == original
    assert all(root.path.is_relative_to(left) for root in first.storage_roots)
    assert all(root.path.is_relative_to(right) for root in second.storage_roots)


@pytest.mark.parametrize("stage", ["read", "write"])
def test_io_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    """验证读样本和临时文件创建失败抛OSError且残留仅在tmp_path，源样本不被改写。"""
    source = FIXTURES / "samples/nav/按任务/libero_10/原始路径.json"
    original = source.read_bytes()
    read = Path.read_text

    def failed_read(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        if path == source:
            raise OSError("sample read failed")
        return read(path, encoding=encoding, errors=errors)

    def failed_write(
        path: Path,
        data: str,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> int:
        assert path.is_relative_to(tmp_path)
        raise OSError("temporary write failed")

    if stage == "read":
        monkeypatch.setattr(Path, "read_text", failed_read)
    else:
        monkeypatch.setattr(Path, "write_text", failed_write)
    with pytest.raises(OSError):
        expand_fake_nav(tmp_path, fixture_dir=FIXTURES)
    assert source.read_bytes() == original
    assert all(path.is_relative_to(tmp_path) for path in tmp_path.rglob("*"))


def test_no_real_mount_access_static() -> None:
    """验收7：静态检查测试代码及fixtures禁止真实挂载路径的文件访问，来源分量只作追溯；检查自身匹配文本和DEFAULT_NAV_ROOT值断言须精确白名单。"""
    from nav_path_audit import fixture_mount_references, python_mount_references

    root = Path(__file__).parent
    for path in root.rglob("*.py"):
        findings = python_mount_references(
            path.read_text(encoding="utf-8"), filename=str(path.relative_to(root))
        )
        assert not findings, (path, findings)
    for path in FIXTURES.rglob("*.json"):
        findings = fixture_mount_references(_json(path), filename=str(path.relative_to(FIXTURES)))
        assert not findings, (path, findings)

    # mountinfo不是JSON；审计所有含路径分隔符的字段，nsfs命名空间标识不是路径。
    mountinfo = root / "fixtures" / "storage" / "mountinfo-sample.txt"
    path_fields = [
        field
        for line in mountinfo.read_text(encoding="utf-8").split("\n")
        for field in line.split(" ")
        if "/" in field
    ]
    assert not fixture_mount_references(path_fields, filename="storage/mountinfo-sample.txt")


def test_no_planning_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验证测试加载路径只在tests/fixtures/nav，禁止打开.scratch、真实home或真实UUID目录。"""
    original = Path.read_text
    reads: list[Path] = []

    def guarded(path: Path, encoding: str | None = None, errors: str | None = None) -> str:
        assert path.is_relative_to(FIXTURES)
        reads.append(path)
        return original(path, encoding=encoding, errors=errors)

    monkeypatch.setattr(Path, "read_text", guarded)
    expand_fake_nav(tmp_path, fixture_dir=FIXTURES)
    assert len(reads) == 33
    assert all(".scratch" not in path.parts for path in reads)


@pytest.mark.parametrize("fault", ["json", "unknown", "realpath", "references", "budget"])
def test_invalid_sample_before_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """样本损坏、未知根、真实路径、引用不一致与超过2MiB均在第一次写入前失败。"""
    source = FIXTURES / "samples/nav/按任务/libero_10/原始路径.json"
    data = _json(source)
    if fault == "references":
        data["sources"][0]["source_id"] = "unselected"
    else:
        data["notes"] = [
            {
                "unknown": "{unknown}/x",
                "realpath": "/" + "mnt/dataset1/x",
                "budget": "x" * (2 * 1024 * 1024),
                "json": "unused",
            }[fault]
        ]
    _inject(monkeypatch, {source: "{" if fault == "json" else json.dumps(data)})
    with pytest.raises(ValueError):
        expand_fake_nav(tmp_path, fixture_dir=FIXTURES)
    assert list(tmp_path.iterdir()) == []


def test_unsafe_expansion_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """展开拒绝非空目录、路径穿越和源样本软链接逃逸，失败不增加目标文件。"""
    existing = tmp_path / "existing"
    existing.mkdir()
    (existing / "keep").write_text("keep", encoding="utf-8")
    with pytest.raises(ValueError):
        expand_fake_nav(existing, fixture_dir=FIXTURES)
    assert [path.name for path in existing.iterdir()] == ["keep"]
    with pytest.raises(ValueError):
        expand_fake_nav(tmp_path / ".." / "outside", fixture_dir=FIXTURES)
    target = tmp_path / "target"
    target.mkdir()
    source = FIXTURES / "samples/nav/按任务/libero_10/原始路径.json"
    original = Path.resolve

    def escaped(path: Path, strict: bool = False) -> Path:
        return tmp_path / "outside-source" if path == source else original(path, strict=strict)

    monkeypatch.setattr(Path, "resolve", escaped)
    with pytest.raises(ValueError):
        expand_fake_nav(target, fixture_dir=FIXTURES)
    assert list(target.iterdir()) == []


def _structured_root_paths(value: object) -> set[str]:
    """递归提取结构化路径；14项Markdown是原文快照，不将正文误当整个路径。"""
    if isinstance(value, str):
        return (
            {value}
            if value.split("/", 1)[0] in {"{nav_root}", "{dataset1}", "{dataset2}"}
            else set()
        )
    if isinstance(value, dict):
        return set[str]().union(
            *(
                _structured_root_paths(item)
                for key, item in cast(dict[str, object], value).items()
                if key != "value_markdown"
            )
        )
    if isinstance(value, list):
        return set[str]().union(
            *(_structured_root_paths(item) for item in cast(list[object], value))
        )
    return set()


def test_structured_references_exist_or_are_recorded_missing(fake_nav: FakeNavigation) -> None:
    """所有结构化根路径必须存在，或逐条登记为历史失效且确实不存在，不凭缺文件反推历史事实。"""
    roots = {
        "{nav_root}": fake_nav.nav_root,
        **{"{" + root.name + "}": root.path for root in fake_nav.storage_roots},
    }
    selections = {item.dataset_id: item for item in fake_nav.manifest.selections}
    unaccounted: set[str] = set()
    for sample in fake_nav.manifest.samples:
        data = _json(FIXTURES / sample.sample_file)
        references = _structured_root_paths(data)
        if not references:
            continue
        missing = set(selections[data["dataset_id"]].retained_missing_paths)
        for reference in references | missing:
            token, *parts = reference.split("/")
            path = roots[token].joinpath(*parts)
            if reference in missing:
                assert not path.exists(), reference
            elif not path.exists():
                unaccounted.add(reference)
    assert not unaccounted, sorted(unaccounted)


def test_truncation_notes_describe_each_dataset() -> None:
    """截短说明按数据集和JSON种类列事实，不把跨盘与alpha删除目录套用到无关数据集。"""
    manifest = NavManifest.model_validate(_json(FIXTURES / "manifest.json"))
    identities = {entry.dataset_id: Path(entry.path).name for entry in manifest.entries}
    for selection in manifest.selections:
        name = identities[selection.dataset_id]
        assert name in selection.explanation
        if name != "agibot_world_alpha":
            assert (
                "agibot_world_alpha" not in selection.explanation
                and "alpha已删除" not in selection.explanation
            )
        if name != "EgoProStandard":
            assert "跨盘" not in selection.explanation
    for sample in manifest.samples:
        parts = Path(sample.asset_path).parts
        name = (
            parts[-2]
            if parts[0] == "nav"
            else ("libero_10" if parts[1] == "dataset1" else "EgoProDemo")
        )
        assert name in sample.truncation
        assert Path(sample.asset_path).name in sample.truncation
        if name != "agibot_world_alpha":
            assert (
                "agibot_world_alpha" not in sample.truncation
                and "alpha已删除" not in sample.truncation
            )
    standard = next(
        s for s in manifest.samples if s.asset_path == "nav/按任务/EgoProStandard/原始路径.json"
    )
    assert all(
        text in standard.truncation
        for text in (
            "734",
            "4",
            "Adjust Seal Sticker",
            "Adjust Shelf Labels",
            "Affix Shipping Label (on Package Surface)",
            "tin's",
        )
    )


def test_mount_path_audit_detects_literal_and_computed_paths() -> None:
    """静态审计须抓住单独挂载根、拼接、Path分段和嵌入段，测试样本文本从不执行。"""
    from nav_path_audit import python_mount_references

    programs = (
        'Path("/mnt")',
        'Path("/" + "mnt")',
        'Path("/") / "mnt"',
        'Path("/", "mnt", "data")',
        'os.path.join("/", "mnt")',
        'Path("/" + "mn" + "t")',
        "Path(f\"/{'mnt'}\")",
        'Path("/data/mnt/a")',
    )
    for program in programs:
        assert python_mount_references(program), program
    for program in ('Path("/tmp/mnt_copy")', 'Path("/tmp/mnt2")'):
        assert not python_mount_references(program), program


def test_mount_path_allowlist_is_exact() -> None:
    """来源例外只限清单规定的分量，源码例外只限完整断言，不能顺带豁免文件访问。"""
    from nav_path_audit import fixture_mount_references, python_mount_references

    provenance = {"samples": [{"source_path_parts": ["mnt", "datasets"]}]}
    assert not fixture_mount_references(provenance, filename="manifest.json")
    assert fixture_mount_references(provenance, filename="sample.json")
    for value in ("/mnt", "/fake/mnt/x", "mnt"):
        assert fixture_mount_references({"path": value}, filename="manifest.json")
    assertion = (
        'def test_defaults():\n    assert DEFAULT_NAV_ROOT.parts == ("/", "mnt", "datasets")\n'
    )
    assert not python_mount_references(assertion, filename="test_storage_config.py")
    assert python_mount_references(
        assertion + '    Path("/mnt").read_text()\n', filename="test_storage_config.py"
    )
