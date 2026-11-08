"""M3-04 创建采集任务关键行为；真实接口与 worker 共用 tests 假导航层。"""

import json
from pathlib import Path

import pytest
from account_api_support import ApiCase
from creation_support import creation_api_case, preview_job, run_queued
from nav_manifest import FakeNavigation

from rdp.jobs.navwrite.pipeline import NavWriteDependencies


def _collection(status: str = "planned") -> dict[str, object]:
    """复用迁移中的首个采集方式和用途，默认不选机器人。"""
    return {"status": status, "method_id": 1, "purpose_id": 1, "robot_ids": []}


@pytest.mark.parametrize("with_format", [False, True])
def test_planned_collection_create_scan_size_and_link(
    tmp_path: Path, fake_nav: FakeNavigation, with_format: bool
) -> None:
    """无链接任务可确认、重扫、筛选、查详情且无错误发现；大小为零，之后能建第一条链接。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        address = str(deps.rescan.roots[0].path / "planned-data")
        selected = [{"format": "mcap"}] if with_format else []
        # 计划地址尚不存在；预览和写导航层都不能创建或读取计划中的数据目录。
        response = api.client.post(
            "/api/datasets/creation-previews",
            json={
                "dataset_name": "计划采集",
                "data_origin": "未知",
                "collection": _collection(),
                "information": {"fields": [{"number": 2, "value_markdown": address}]},
                "format_entries": selected,
            },
        )
        assert response.status_code == 201, response.text
        preview_id = response.json()["job_id"]
        result = run_queued(api, deps, preview_id)
        assert result.summary is not None and not result.summary.aborted
        preview = api.client.get(f"/api/datasets/creation-previews/{preview_id}").json()
        assert preview["parameters"]["link"] is None
        details = preview["report"]["creation"]
        assert details["links"] == details["sources_added"] == details["dataset_roots_added"] == []
        assert details["metadata_source"] == "not_checked"
        changes = preview["report"]["listed_changes"]
        assert any(item["json_path"] == "collection" for item in changes)
        assert any(
            item["json_path"] == "data_origin" and json.loads(item["after"]) == "真机采集"
            for item in changes
        )
        canonical = deps.rescan.nav_root / "按任务/计划采集"
        assert not canonical.exists()
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": preview_id}
        )
        assert submitted.status_code == 201, submitted.text
        written = run_queued(api, deps, submitted.json()["job_id"])
        assert written.summary is not None and not written.summary.aborted
        assert not Path(address).exists()
        information = json.loads((canonical / "数据集信息.json").read_bytes())
        manifest = json.loads((canonical / "原始路径.json").read_bytes())
        assert information["collection"] == _collection()
        assert information["fields"][1]["value_markdown"] == address
        assert information["data_origin"] == "真机采集"
        assert manifest["links"] == manifest["sources"] == manifest["dataset_roots"] == []
        assert not any(path.is_symlink() for path in canonical.iterdir())
        if with_format:
            replica = deps.rescan.nav_root / "按格式/mcap/计划采集"
            assert (replica / "数据集信息.json").read_bytes() == (
                canonical / "数据集信息.json"
            ).read_bytes()
            assert json.loads((replica / "原始路径.json").read_bytes())["links"] == []
        identifier = manifest["dataset_id"]
        _check_scan_and_size(api, deps, identifier, canonical)
        _check_first_link(api, deps, fake_nav, identifier, address)


def _check_scan_and_size(
    api: ApiCase, deps: NavWriteDependencies, identifier: str, canonical: Path
) -> None:
    """验证空任务的导航重建、筛选、详情、面板和零字节统计。"""
    # 显式重扫证明数据完全从导航层恢复，不依赖创建作业的内存状态。
    scan = api.client.post(f"/api/datasets/{identifier}/rescan")
    assert scan.status_code == 201, scan.text
    scanned = run_queued(api, deps, scan.json()["job_id"])
    assert scanned.summary is not None and not scanned.summary.aborted
    listing = api.client.get("/api/datasets", params={"collection_status": "planned"}).json()
    assert [item["dataset_id"] for item in listing["items"]] == [identifier]
    detail = api.client.get("/api/datasets/detail", params={"entry_path": "按任务/计划采集"}).json()
    assert not detail["index_stale"]
    assert detail["links"] == detail["sources"] == []
    assert detail["collection"]["status"] == "planned"
    panel = api.client.get("/api/datasets/panel", params={"dataset_id": identifier}).json()
    assert all(item["severity"] != "action_required" for item in panel["findings"])

    # 写入流程已排队大小统计；运行实际作业，空链接的总和必须发布为 0。
    jobs = api.client.get("/api/jobs").json()["items"]
    sizing = next(
        item for item in jobs if item["type_name"] == "dataset_sizing" and item["state"] == "queued"
    )
    sized = run_queued(api, deps, sizing["job_id"])
    assert sized.summary is not None and not sized.summary.aborted
    detail = api.client.get("/api/datasets/detail", params={"entry_path": "按任务/计划采集"}).json()
    assert detail["dataset_size"]["display_bytes"] == 0
    # 先完成自动大小回写，随后建链的队列确认只涉及本次新链接。
    jobs = api.client.get("/api/jobs").json()["items"]
    sync = next(item for item in jobs if item["type_name"] == "nav_size_sync")
    synced = run_queued(api, deps, sync["job_id"])
    assert synced.summary is not None and not synced.summary.aborted
    assert (
        "0 B"
        in json.loads((canonical / "数据集信息.json").read_bytes())["fields"][3]["value_markdown"]
    )


def _check_first_link(
    api: ApiCase,
    deps: NavWriteDependencies,
    fake_nav: FakeNavigation,
    identifier: str,
    address: str,
) -> None:
    """验证空任务能追加首条链接与数据块，并同步新建或已有的格式入口。"""
    canonical = deps.rescan.nav_root / "按任务/计划采集"
    Path(address).mkdir()
    link_preview = preview_job(
        api,
        deps,
        fake_nav,
        dataset_id=identifier,
        link={"name": "原始数据", "target_path": address, "fallback_format": "mcap"},
        format_entries=[{"format": "mcap"}],
    )
    submitted = api.client.post(
        "/api/datasets/creation-writes", json={"preview_job_id": link_preview}
    )
    assert submitted.status_code == 201, submitted.text
    linked = run_queued(api, deps, submitted.json()["job_id"])
    assert linked.summary is not None and not linked.summary.aborted
    assert (canonical / "原始数据").readlink() == Path(address)
    replica = deps.rescan.nav_root / "按格式/mcap/计划采集"
    assert (replica / "原始数据").readlink() == Path(address)
    manifest = json.loads((canonical / "原始路径.json").read_bytes())
    assert len(manifest["links"]) == len(manifest["sources"]) == 1
    assert manifest["dataset_roots"] == [address]
    assert json.loads((canonical / "数据集信息.json").read_bytes())["collection"] == _collection()


@pytest.mark.parametrize(
    "changes",
    [
        {},
        {"collection": None},
        {"collection": _collection("collecting")},
        {"collection": _collection("done")},
        {"collection": _collection(), "information": None},
        {"collection": _collection(), "information": {"fields": []}},
        {
            "collection": _collection(),
            "information": {"fields": [{"number": 2, "value_markdown": " \n\t "}]},
        },
    ],
)
def test_creation_requires_link_or_planned_address(
    tmp_path: Path, fake_nav: FakeNavigation, changes: dict[str, object]
) -> None:
    """无链接只允许计划中且地址非空的采集任务，其余参数在 HTTP 入口返回 422。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        body = {
            "dataset_name": "参数拒绝",
            "data_origin": "未知",
            "link": None,
            "information": {"fields": [{"number": 2, "value_markdown": "计划位置"}]},
        } | changes
        response = api.client.post("/api/datasets/creation-previews", json=body)
        assert response.status_code == 422, response.text
        assert not (deps.rescan.nav_root / "按任务/参数拒绝").exists()


@pytest.mark.parametrize("field", ["method_id", "purpose_id", "robot_ids"])
@pytest.mark.parametrize("retired", [False, True])
def test_creation_rejects_missing_or_retired_collection_reference(
    tmp_path: Path, fake_nav: FakeNavigation, field: str, retired: bool
) -> None:
    """创建预览复用登记校验，不存在或停用的机器人、方式和用途均拒绝，导航不落盘。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        collection = _collection()
        if retired:
            if field == "robot_ids":
                assert (
                    api.client.post(
                        "/api/robots", json={"name": "一号", "robot_model": "R1"}
                    ).status_code
                    == 201
                )
                url = "/api/robots/1"
            else:
                kind = "methods" if field == "method_id" else "purposes"
                url = f"/api/collection-vocabulary/{kind}/1"
            assert api.client.post(url + "/retire").status_code == 200
        identifier = 1 if retired else 999
        collection[field] = [identifier] if field == "robot_ids" else identifier
        preview = preview_job(
            api,
            deps,
            fake_nav,
            operation="dataset",
            execute=False,
            link=None,
            collection=collection,
            information={"fields": [{"number": 2, "value_markdown": "计划位置"}]},
        )
        result = run_queued(api, deps, preview)
        assert result.summary is not None and result.summary.aborted
        assert api.client.get(f"/api/datasets/creation-previews/{preview}").status_code == 400
        assert not (deps.rescan.nav_root / "按任务/接口新数据集").exists()


@pytest.mark.parametrize("origin", ["未知", "仿真生成"])
def test_creation_with_link_preserves_collection_and_explicit_origin(
    tmp_path: Path, fake_nav: FakeNavigation, origin: str
) -> None:
    """带链接可以创建非计划中任务；采集信息同步格式副本，来源只在未知时自动带出。"""
    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        response = api.client.post("/api/robots", json={"name": "一号", "robot_model": "R1"})
        assert response.status_code == 201, response.text
        collection = _collection("done") | {"robot_ids": [1, 1]}
        preview = preview_job(
            api,
            deps,
            fake_nav,
            operation="dataset",
            collection=collection,
            data_origin=origin,
            format_entries=[{"format": "mcap"}],
        )
        response = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": preview}
        )
        assert response.status_code == 201, response.text
        result = run_queued(api, deps, response.json()["job_id"])
        assert result.summary is not None and not result.summary.aborted
        canonical = deps.rescan.nav_root / "按任务/接口新数据集/数据集信息.json"
        replica = deps.rescan.nav_root / "按格式/mcap/接口新数据集/数据集信息.json"
        assert canonical.read_bytes() == replica.read_bytes()
        information = json.loads(canonical.read_bytes())
        assert information["collection"] == _collection("done") | {"robot_ids": [1]}
        assert information["data_origin"] == ("真机采集" if origin == "未知" else origin)
        assert api.client.get("/api/robots").json()["items"][0]["reference_count"] == 1
