"""M1.5-02：经真实 HTTP、worker 和假导航层验证编辑契约，不访问真实数据。"""

import json
from pathlib import Path

from data_origin_support import run_submitted
from dataset_api_support import browser_case, set_meta
from nav_manifest import FakeNavigation
from navwrite_support import dataset_id_of, tree_state

# 首尾空格与换行用于确认子任务记事本原文不会被分类字段的规范化逻辑改写。
SUBTASK_NOTES = " 抓取杯子\n移动到桌面\n放下杯子 "


def test_information_edit_syncs_and_reverts(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：子任务缺失投影为空串；多行原文及分类编辑经只读预览、同步两视图并可撤回。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        before = tree_state(fake_nav.nav_root)
        page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "数据集信息.json"}
        )
        assert page.status_code == 200, page.text
        data = page.json()
        assert data["entry_path"] == "按任务/libero_10"
        assert {
            item["path"][0]: item
            for item in data["fields"]
            if item["path"] in (["subtask_notes"], ["scene"])
        } == {
            "subtask_notes": {
                "path": ["subtask_notes"],
                "label": "子任务",
                "value": "",
                "multiple": False,
            },
            "scene": {"path": ["scene"], "label": "场景", "value": [], "multiple": True},
        }
        changes = [
            {"path": ["title"], "value": "新的标题"},
            {"path": ["robot_model"], "value": "Franka"},
            {"path": ["scene"], "value": [" tabletop ", "kitchen", "tabletop"]},
            {"path": ["tasks"], "value": [" a ", "a", "b"]},
            {"path": ["subtask_notes"], "value": SUBTASK_NOTES},
            {"path": ["fields", 5, "value_markdown"], "value": "新的第六项"},
        ]
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": dataset,
                "changes": [
                    {"document": "数据集信息.json", "expected_sha256": data["sha256"], **change}
                    for change in changes
                ],
            },
        )
        assert response.status_code == 201, response.text
        preview_id = int(response.json()["job_id"])
        preview = run_submitted(case, fake_nav, preview_id)
        assert preview.summary is not None and not preview.summary.aborted
        report = case.client.get(f"/api/navigation/previews/{preview_id}").json()
        assert report["operation"] == "edit_dataset_fields"
        assert report["report"]["listed_total"] >= 5
        assert tree_state(fake_nav.nav_root) == before
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview_id}},
        )
        apply_id = int(response.json()["job_id"])
        applied = run_submitted(case, fake_nav, apply_id)
        assert applied.summary is not None and not applied.summary.aborted
        root = fake_nav.nav_root
        canonical = json.loads((root / "按任务/libero_10/数据集信息.json").read_bytes())
        replica = json.loads((root / "按格式/lerobot/3.0/libero_10/数据集信息.json").read_bytes())
        assert canonical == replica and canonical["subtask_notes"] == SUBTASK_NOTES
        assert (
            canonical["title"] == "新的标题"
            and canonical["fields"][5]["value_markdown"] == "新的第六项"
        )
        assert (canonical["robot_model"], canonical["scene"], canonical["tasks"]) == (
            "Franka",
            ["tabletop", "kitchen"],
            ["a", "b"],
        )
        logs = case.client.get("/api/audit/operations", params={"operation": "edit_dataset_fields"})
        assert logs.status_code == 200, logs.text
        assert str(apply_id) in logs.text
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_revert_preview", "parameters": {"target_job_id": apply_id}},
        )
        reverse_id = int(response.json()["job_id"])
        reverse = run_submitted(case, fake_nav, reverse_id)
        assert reverse.summary is not None and not reverse.summary.aborted
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": reverse_id}},
        )
        undone = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert undone.summary is not None and not undone.summary.aborted
        assert tree_state(root) == before


def test_reserved_scene_is_rejected(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：场景保留字 unlabeled 在真实 HTTP 入口返回 422，不进入写入流程。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": dataset,
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["scene"],
                        "value": ["unlabeled"],
                    }
                ],
            },
        )
        assert response.status_code == 422, response.text
        assert response.json()["diagnostics"][0]["rule"] == "NAV_FIELDS"


def test_paged_subtasks_and_source_annotations(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：子任务按条目分页，仅提交修改项；名称、描述、数据块关系与说明同步格式副本，推导字段重建。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "EgoProDemo")
        root = fake_nav.nav_root
        # 人工写坏推导字段，编辑必须按目录重算，不能沿用 JSON 自称的位置。
        path = root / "按任务/EgoProDemo/原始路径.json"
        manifest = json.loads(path.read_bytes())
        manifest["view"] = "format"
        manifest["sources"][0]["entry_path"] = "错误位置"
        path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        response = case.client.get(
            f"/api/datasets/{dataset}/editable-fields",
            params={"document": "子任务.json", "limit": 1},
        )
        assert response.status_code == 200, response.text
        first = response.json()
        assert first["total"] == 2 and first["offset"] == 0
        assert len(first["fields"]) == 3
        assert all(item["path"][1] == 0 for item in first["fields"])
        second = case.client.get(
            f"/api/datasets/{dataset}/editable-fields",
            params={"document": "子任务.json", "offset": 1, "limit": 1},
        ).json()
        assert second["sha256"] == first["sha256"] and second["fields"][0]["path"] == [
            "tasks",
            1,
            "display_name",
        ]
        source_page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields",
            params={"document": "原始路径.json", "limit": 1},
        ).json()
        edits = [
            {
                "document": "子任务.json",
                "expected_sha256": first["sha256"],
                "path": ["tasks", 0, "display_name"],
                "value": "贴标",
            },
            {
                "document": "子任务.json",
                "expected_sha256": first["sha256"],
                "path": ["tasks", 0, "description"],
                "value": "人工确认的描述",
            },
            {
                "document": "子任务.json",
                "expected_sha256": first["sha256"],
                "path": ["tasks", 0, "source_ids"],
                "value": ["src_accf48ec594b"],
            },
            {
                "document": "原始路径.json",
                "expected_sha256": source_page["sha256"],
                "path": ["sources", 0, "source_role"],
                "value": "人工核验",
            },
            {
                "document": "原始路径.json",
                "expected_sha256": source_page["sha256"],
                "path": ["sources", 0, "validation_status"],
                "value": "reviewed_by_operator",
            },
        ]
        response = case.client.post(
            "/api/navigation/fields/preview", json={"dataset_id": dataset, "changes": edits}
        )
        assert response.status_code == 201, response.text
        preview_id = int(response.json()["job_id"])
        preview = run_submitted(case, fake_nav, preview_id)
        assert preview.summary is not None and not preview.summary.aborted
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview_id}},
        )
        result = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert result.summary is not None and not result.summary.aborted
        for entry in ("按任务/EgoProDemo", "按格式/lerobot/3.0/EgoProDemo"):
            tasks = json.loads((root / entry / "子任务.json").read_bytes())["tasks"]
            assert (
                tasks[0]["display_name"] == "贴标" and tasks[0]["description"] == "人工确认的描述"
            )
            assert [item["source_id"] for item in tasks[0]["sources"]] == ["src_accf48ec594b"]
            original = json.loads((root / entry / "原始路径.json").read_bytes())
            assert original["view"] == ("task" if entry.startswith("按任务") else "format")
            assert original["sources"][0]["source_role"] == "人工核验"
            assert original["sources"][0]["validation_status"] == "reviewed_by_operator"
            assert original["sources"][0]["entry_path"].startswith(entry + "/原始数据/")


def test_read_refuses_unknown_dataset_and_bad_json_safely(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：缺失、软链接和损坏文件返回业务诊断；不越过导航边界、不读其他数据集的坏文件。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        root = fake_nav.nav_root
        unrelated = root / "按任务/EgoProDemo/数据集信息.json"
        unrelated.write_bytes(b"bad json")
        url = f"/api/datasets/{dataset}/editable-fields"
        params = {"document": "数据集信息.json"}
        assert case.client.get(url, params=params).status_code == 200
        path = root / "按任务/libero_10/数据集信息.json"
        path.unlink()
        missing = case.client.get(url, params=params)
        assert missing.status_code == 400, missing.text
        path.symlink_to(unrelated)
        linked = case.client.get(url, params=params)
        assert linked.status_code == 400, linked.text
        path.unlink()
        path.write_bytes(b"{bad")
        invalid = case.client.get(url, params=params)
        assert invalid.status_code == 400, invalid.text
        assert invalid.json()["diagnostics"][0]["objects"]


def test_confirm_conflict_and_worker_conflict_write_nothing(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：确认时过期返回409；确认后再变化由锁内复核拒绝，两个时点都一行不写。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        data = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": dataset,
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": data["sha256"],
                        "path": ["robot_model"],
                        "value": "新型号",
                    }
                ],
            },
        )
        identifier = int(response.json()["job_id"])
        run_submitted(case, fake_nav, identifier)
        path = fake_nav.nav_root / "按任务/libero_10/子任务.json"
        raw = path.read_bytes()
        path.write_bytes(raw + b"\n")
        before = tree_state(fake_nav.nav_root)
        rejected = case.client.post(f"/api/navigation/fields/previews/{identifier}/apply")
        assert rejected.status_code == 409, rejected.text
        assert tree_state(fake_nav.nav_root) == before
        path.write_bytes(raw)
        response = case.client.post(f"/api/navigation/fields/previews/{identifier}/apply")
        assert response.status_code == 201, response.text
        path.write_bytes(raw + b"\n")
        applied = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert applied.summary is not None and applied.summary.aborted
        assert applied.diagnostics[0].samples[0].category.value == "conflict"
        assert tree_state(fake_nav.nav_root) == before


def test_invalid_field_requests_are_rejected_before_queueing(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：非法字段、子任务数组等错误类型、重复补丁及越界分页返回422，不进入作业参数。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        valid = {
            "document": "数据集信息.json",
            "expected_sha256": "a" * 64,
            "path": ["title"],
            "value": "新标题",
        }
        for change in (
            valid | {"path": ["dataset_id"]},
            valid | {"path": ["view"]},
            valid | {"document": "原始路径.json", "path": ["sources", 0, "direct_path"]},
            valid | {"path": ["scene"], "value": "单个字符串"},
            valid | {"path": ["subtask_notes"], "value": ["抓取杯子", "放下杯子"]},
            valid | {"path": ["tasks"], "value": "不是数组"},
            valid | {"path": ["fields", True, "value_markdown"]},
        ):
            response = case.client.post(
                "/api/navigation/fields/preview", json={"dataset_id": dataset, "changes": [change]}
            )
            assert response.status_code == 422, response.text
        duplicate = case.client.post(
            "/api/navigation/fields/preview",
            json={"dataset_id": dataset, "changes": [valid, valid]},
        )
        assert duplicate.status_code == 422, duplicate.text
        assert (
            case.client.get(
                f"/api/datasets/{dataset}/editable-fields",
                params={"document": "子任务.json", "limit": 21},
            ).status_code
            == 422
        )


def test_preview_explains_replica_rebuild_and_model_reference(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：型号参考来自索引的原文件事实，副本重建的推导修正和被筛引用必须可见，未知键保留。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        set_meta(case, "按任务/libero_10", "franka")
        url = f"/api/datasets/{dataset}/editable-fields"
        page = case.client.get(url, params={"document": "数据集信息.json"}).json()
        assert page["original_robot_types"] == ["franka"]
        path = fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/原始路径.json"
        payload = json.loads(path.read_bytes())
        payload["view"] = "task"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        info = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
        original = json.loads(info.read_bytes())
        original["unknown_extension"] = {"保留": [1, True]}
        info.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        page = case.client.get(url, params={"document": "数据集信息.json"}).json()
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": dataset,
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["robot_model"],
                        "value": "手动型号",
                    }
                ],
            },
        )
        identifier = int(response.json()["job_id"])
        result = run_submitted(case, fake_nav, identifier)
        assert result.summary is not None and not result.summary.aborted
        report = case.client.get(f"/api/navigation/previews/{identifier}").json()["report"]
        assert any(
            item["file"] == "按格式/lerobot/3.0/libero_10/原始路径.json"
            and item["json_path"] == "view"
            and item["before"] == '"task"'
            and item["after"] == '"format"'
            for item in report["listed_changes"]
        )
        response = case.client.post(f"/api/navigation/fields/previews/{identifier}/apply")
        applied = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert applied.summary is not None and not applied.summary.aborted
        for entry in ("按任务/libero_10", "按格式/lerobot/3.0/libero_10"):
            assert json.loads((fake_nav.nav_root / entry / "数据集信息.json").read_bytes())[
                "unknown_extension"
            ] == {"保留": [1, True]}


def test_ambiguous_identity_and_stale_form_refuse_preview(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：三份文件身份不一致时拒绝；填表期间改文件时冲突；都保留现场且不保存可执行预览。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        payload = {
            "dataset_id": dataset,
            "changes": [
                {
                    "document": "数据集信息.json",
                    "expected_sha256": page["sha256"],
                    "path": ["title"],
                    "value": "新标题",
                }
            ],
        }
        path = fake_nav.nav_root / "按任务/libero_10/子任务.json"
        raw = path.read_bytes()
        corrupted = json.loads(raw)
        corrupted["dataset_id"] = "dataset-other"
        path.write_text(json.dumps(corrupted, ensure_ascii=False), encoding="utf-8")
        before = tree_state(fake_nav.nav_root)
        response = case.client.post("/api/navigation/fields/preview", json=payload)
        identifier = int(response.json()["job_id"])
        result = run_submitted(case, fake_nav, identifier)
        assert result.summary is not None and result.summary.aborted
        diagnostic = result.diagnostics[0].samples[0]
        assert diagnostic.category.value == "input"
        assert any(obj.key == "dataset_id" and obj.value == dataset for obj in diagnostic.objects)
        assert tree_state(fake_nav.nav_root) == before
        path.write_bytes(raw)
        info = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
        info.write_bytes(info.read_bytes() + b"\n")
        before = tree_state(fake_nav.nav_root)
        response = case.client.post("/api/navigation/fields/preview", json=payload)
        identifier = int(response.json()["job_id"])
        result = run_submitted(case, fake_nav, identifier)
        assert result.summary is not None and result.summary.aborted
        assert result.diagnostics[0].samples[0].category.value == "conflict"
        assert tree_state(fake_nav.nav_root) == before
        assert not (case.app.state.job_paths.nav_previews / f"{identifier}.json.gz").exists()


def test_relationship_edits_use_unchanged_registered_sources(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：同批移交关联不会因前一项删除旧引用而丢失候选；未知数据块以输入错误拒绝且不写。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "EgoProDemo")
        page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "子任务.json"}
        ).json()
        payload = {
            "dataset_id": dataset,
            "changes": [
                {
                    "document": "子任务.json",
                    "expected_sha256": page["sha256"],
                    "path": ["tasks", 0, "source_ids"],
                    "value": [],
                },
                {
                    "document": "子任务.json",
                    "expected_sha256": page["sha256"],
                    "path": ["tasks", 1, "source_ids"],
                    "value": ["src_4d589639da3c"],
                },
            ],
        }
        before = tree_state(fake_nav.nav_root)
        response = case.client.post("/api/navigation/fields/preview", json=payload)
        identifier = int(response.json()["job_id"])
        result = run_submitted(case, fake_nav, identifier)
        assert result.summary is not None and not result.summary.aborted
        assert tree_state(fake_nav.nav_root) == before
        payload = {
            "dataset_id": dataset,
            "changes": [
                {
                    "document": "子任务.json",
                    "expected_sha256": page["sha256"],
                    "path": ["tasks", 1, "source_ids"],
                    "value": ["unregistered-source"],
                }
            ],
        }
        response = case.client.post("/api/navigation/fields/preview", json=payload)
        result = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert result.summary is not None and result.summary.aborted
        diagnostic = result.diagnostics[0].samples[0]
        assert diagnostic.category.value == "input"
        assert any(obj.key == "dataset_id" and obj.value == dataset for obj in diagnostic.objects)
        assert tree_state(fake_nav.nav_root) == before


def test_missing_derived_null_is_reported(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：L10补写显式null也是实际差异，不能与字段缺失混同而藏在文件写入中。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        path = fake_nav.nav_root / "按任务/libero_10/原始路径.json"
        payload = json.loads(path.read_bytes())
        payload.pop("version", None)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": dataset,
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["title"],
                        "value": "新标题",
                    }
                ],
            },
        )
        identifier = int(response.json()["job_id"])
        result = run_submitted(case, fake_nav, identifier)
        assert result.summary is not None and not result.summary.aborted
        report = case.client.get(f"/api/navigation/previews/{identifier}").json()["report"]
        assert any(
            item["file"] == "按任务/libero_10/原始路径.json"
            and item["json_path"] == "version"
            and "字段不存在" in item["before"]
            and item["after"] == "null"
            for item in report["listed_changes"]
        )


def test_size_is_automatic(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """M1.5-07：第 4 项自由文字不产生缺记录诊断，不可编辑且 HTTP 拒绝修改为 422。"""
    path = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    payload = json.loads(path.read_bytes())
    payload["fields"][3]["value_markdown"] = "119.643 GB"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        panel = case.client.get("/api/datasets/panel")
        assert panel.status_code == 200, panel.text
        assert "RECORDED_SIZE_MISSING" not in panel.text
        page = case.client.get(
            f"/api/datasets/{dataset}/editable-fields", params={"document": "数据集信息.json"}
        ).json()
        assert not any(field["path"] == ["fields", 3, "value_markdown"] for field in page["fields"])
        response = case.client.post(
            "/api/navigation/fields/preview",
            json={
                "dataset_id": dataset,
                "changes": [
                    {
                        "document": "数据集信息.json",
                        "expected_sha256": page["sha256"],
                        "path": ["fields", 3, "value_markdown"],
                        "value": "0 B",
                    }
                ],
            },
        )
        assert response.status_code == 422, response.text
