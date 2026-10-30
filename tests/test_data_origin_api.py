"""M1-10 HTTP 契约：成员提交预览、读取报告，再确认写入；所有路径属于临时假导航层。"""

import json
from pathlib import Path

from data_origin_support import run_submitted
from dataset_api_support import browser_case
from nav_manifest import FakeNavigation
from navwrite_support import audit_details, dataset_id_of, tree_state
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.infra.db.connection import session_scope
from rdp.jobs.types import JobState


def test_http_preview_submission_and_report(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：接口只提交只读预览；worker 完成后可读取报告，导航层仍未改动。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        before = tree_state(fake_nav.nav_root)
        dataset = dataset_id_of(fake_nav, "libero_10")
        response = case.client.post(
            "/api/navigation/data-origin/preview",
            json={"dataset_id": dataset, "data_origin": "开源下载"},
        )
        assert response.status_code == 201, response.text
        job = response.json()
        assert job["type_name"] == "nav_data_origin_preview" and job["state"] == "queued"
        result = run_submitted(case, fake_nav, int(job["job_id"]))
        assert (
            result.state is JobState.COMPLETED
            and result.summary is not None
            and not result.summary.aborted
        )
        response = case.client.get(f"/api/navigation/previews/{job['job_id']}")
        assert response.status_code == 200, response.text
        report = response.json()["report"]
        assert report["listed_changes"][0]["before"] == "未知"
        assert report["listed_changes"][0]["after"] == "开源下载"
        assert tree_state(fake_nav.nav_root) == before


def test_apply_reindexes_audits_and_reverts(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验收：新建来源后同作业更新来源筛选及面板，日志带变更编号，撤回删除新文件并恢复未知。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        response = case.client.post(
            "/api/navigation/data-origin/preview",
            json={"dataset_id": dataset, "data_origin": "开源下载"},
        )
        preview_id = int(response.json()["job_id"])
        run_submitted(case, fake_nav, preview_id)
        response = case.client.post(
            "/api/jobs",
            json={
                "type_name": "nav_write_apply",
                "parameters": {"preview_job_id": preview_id},
            },
        )
        assert response.status_code == 201, response.text
        apply_id = int(response.json()["job_id"])
        result = run_submitted(case, fake_nav, apply_id)
        assert result.summary is not None and not result.summary.aborted
        path = fake_nav.nav_root / "按任务/libero_10/来源.json"
        payload = json.loads(path.read_bytes())
        assert payload["data_origin"] == "开源下载" and payload["lineage"] == []
        assert payload["data_origin_set_by"]["account_name"] == "管理员"
        assert not (fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/来源.json").exists()
        response = case.client.get("/api/datasets", params={"data_origin": "open_source"})
        assert response.status_code == 200, response.text
        assert [item["dataset_id"] for item in response.json()["items"]] == [dataset]
        panel = case.client.get("/api/datasets/panel", params={"dataset_id": dataset})
        assert "PROVENANCE_MISSING" not in panel.text
        with session_scope(case.engine, read_only=True) as session:
            rows = tuple(
                session.scalars(
                    select(OperationLogRow).where(
                        OperationLogRow.object_kind == "navigation_write",
                        OperationLogRow.object_id == str(apply_id),
                    )
                )
            )
            assert len(rows) == 1
            assert audit_details(rows[0])["after"]["change_record_id"] == str(apply_id)
        response = case.client.post(
            "/api/jobs",
            json={
                "type_name": "nav_revert_preview",
                "parameters": {"target_job_id": apply_id},
            },
        )
        revert_preview = int(response.json()["job_id"])
        run_submitted(case, fake_nav, revert_preview)
        response = case.client.get(f"/api/navigation/previews/{revert_preview}")
        assert response.status_code == 200 and response.json()["operation"] == "revert_change"
        response = case.client.post(
            "/api/jobs",
            json={
                "type_name": "nav_write_apply",
                "parameters": {"preview_job_id": revert_preview},
            },
        )
        undone = run_submitted(case, fake_nav, int(response.json()["job_id"]))
        assert undone.summary is not None and not undone.summary.aborted
        assert not path.exists()
        assert (
            case.client.get("/api/datasets", params={"data_origin": "open_source"}).json()["items"]
            == []
        )
        assert (
            "PROVENANCE_MISSING"
            in case.client.get("/api/datasets/panel", params={"dataset_id": dataset}).text
        )


def test_member_can_preview_and_invalid_requests_are_safe(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：成员可标注，服务端拒绝非法来源、路径、身份伪造、非法作业号及未完成报告；未登录/跨源仍受全局鉴权。"""
    from accounts_support import EXAMPLE_SECRET

    with browser_case(tmp_path / "state", fake_nav) as case:
        created = case.client.post(
            "/api/accounts",
            json={
                "login_name": "member",
                "password": EXAMPLE_SECRET.get_secret_value(),
                "display_name": "成员",
                "role": "member",
            },
        )
        assert created.status_code == 201, created.text
        assert case.login("member").status_code == 200
        # 新建成员必须先改密；改密接口继续使用第 06 张的真实认证流程。
        changed = case.client.post(
            "/api/auth/password",
            json={
                "current_password": EXAMPLE_SECRET.get_secret_value(),
                "new_password": "MemberNewPassword-123!",
            },
        )
        assert changed.status_code == 200, changed.text
        payload = {"dataset_id": dataset_id_of(fake_nav, "libero_10"), "data_origin": "开源下载"}
        response = case.client.post("/api/navigation/data-origin/preview", json=payload)
        assert response.status_code == 201, response.text
        identifier = response.json()["job_id"]
        assert case.client.get(f"/api/navigation/previews/{identifier}").status_code == 400
        assert case.client.get("/api/navigation/previews/99999").status_code == 404
        assert case.client.get("/api/navigation/previews/01").status_code == 422
        for bad in (
            payload | {"data_origin": "made-up"},
            payload | {"dataset_id": "../outside"},
            payload | {"account_id": 1},
            payload | {"data_origin": None},
        ):
            rejected = case.client.post("/api/navigation/data-origin/preview", json=bad)
            assert rejected.status_code == 422, rejected.text
            assert "made-up" not in rejected.text and "../outside" not in rejected.text
        rejected = case.client.post(
            "/api/navigation/data-origin/preview",
            json=payload,
            headers={"Origin": "http://elsewhere"},
        )
        assert rejected.status_code == 403
        case.client.cookies.clear()
        assert (
            case.client.post("/api/navigation/data-origin/preview", json=payload).status_code == 401
        )


def test_origin_filter_counts_follow_index(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：标注后筛选候选的来源计数来自新索引，不能继续把全部数据集算进未知。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        dataset = dataset_id_of(fake_nav, "libero_10")
        response = case.client.post(
            "/api/navigation/data-origin/preview",
            json={"dataset_id": dataset, "data_origin": "开源下载"},
        )
        preview_id = int(response.json()["job_id"])
        run_submitted(case, fake_nav, preview_id)
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": preview_id}},
        )
        run_submitted(case, fake_nav, int(response.json()["job_id"]))
        filters = case.client.get("/api/datasets/filters").json()
        counts = {item["value"]: item["count"] for item in filters["data_origins"]}
        assert counts == {
            "real": 0,
            "umi": 0,
            "ego": 0,
            "simulation": 0,
            "open_source": 1,
            "unknown": 4,
        }


def test_detail_reports_unmarked_origin_in_both_views(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """评审回归：两种视图的详情都报告规范入口尚无来源文件，未知与已标注未知不能混淆。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        for entry in ("按任务/libero_10", "按格式/lerobot/3.0/libero_10"):
            response = case.client.get("/api/datasets/detail", params={"entry_path": entry})
            assert response.status_code == 200, response.text
            assert response.json()["provenance"] == {
                "state": "absent",
                "data_origin": "未知",
                "data_origin_set_by": None,
            }


def test_detail_reads_current_origin_stamp_from_canonical(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """评审回归：详情只读规范入口当前来源和印记，两视图一致；不需要先重扫，不信任格式入口伪副本。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        payload = json.loads(
            (Path(__file__).parent / "fixtures/provenance-draft.json").read_bytes()
        )
        payload.update(dataset_id="dataset-14", dataset_name="libero_10", data_origin="仿真生成")
        payload["data_origin_set_by"] = {
            "kind": "人工标注",
            "account_id": 7,
            "account_name": "标注成员",
            "at": "2026-10-30T07:00:00Z",
        }
        (fake_nav.nav_root / "按任务/libero_10/来源.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        # 格式入口即使误放来源副本，也不能替代规范入口的当前值。
        (fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/来源.json").write_text(
            json.dumps(payload | {"data_origin": "开源下载"}, ensure_ascii=False), encoding="utf-8"
        )
        before = tree_state(fake_nav.nav_root)
        for entry in ("按任务/libero_10", "按格式/lerobot/3.0/libero_10"):
            response = case.client.get("/api/datasets/detail", params={"entry_path": entry})
            assert response.status_code == 200, response.text
            assert response.json()["provenance"] == {
                "state": "valid",
                "data_origin": "仿真生成",
                "data_origin_set_by": {"account_name": "标注成员", "at": "2026-10-30T07:00:00Z"},
            }
            assert response.json()["index_stale"] is True
        assert tree_state(fake_nav.nav_root) == before
