"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

from pathlib import Path

from nav_manifest import FakeNavigation


def test_changed_json_conflicts_without_write(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：验收 4/L12：临时导航预览后改变 JSON，在第 07 张流水线写锁下冲突，逐字节证明一行未写。"""
    import json

    from creation_support import creation_api_case, preview_job, run_queued
    from navwrite_support import tree_state

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        identifier = preview_job(api, deps, fake_nav)
        path = deps.rescan.nav_root / "按任务/EgoProDemo/原始路径.json"
        value = json.loads(path.read_text())
        value["external_change"] = 1
        path.write_text(json.dumps(value))
        before = tree_state(deps.rescan.nav_root)
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert submitted.status_code == 201, submitted.text
        record = run_queued(api, deps, submitted.json()["job_id"])
        assert record.summary is not None and record.summary.aborted
        assert tree_state(deps.rescan.nav_root) == before
        body = api.client.get(f"/api/jobs/{record.job_id}").json()
        assert any(
            item["category"] == "conflict"
            for group in body["diagnostics"]
            for item in group["samples"]
        )


def test_changed_link_and_names_conflict(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L12：修改链接目标、删除入口或新增条目分别触发冲突，列出实际/期望及重新预览建议。"""
    from creation_support import creation_api_case, preview_job, run_queued
    from navwrite_support import tree_state

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        for mutation in ("link", "names"):
            identifier = preview_job(api, deps, fake_nav)
            root = deps.rescan.nav_root / "按任务/EgoProDemo"
            if mutation == "link":
                link = root / "原始数据"
                link.unlink()
                link.symlink_to(deps.rescan.roots[0].path)
            else:
                (root / "extra-entry").write_text("x")
            before = tree_state(deps.rescan.nav_root)
            submitted = api.client.post(
                "/api/datasets/creation-writes", json={"preview_job_id": identifier}
            )
            record = run_queued(api, deps, submitted.json()["job_id"])
            assert record.summary is not None and record.summary.aborted
            assert tree_state(deps.rescan.nav_root) == before


def test_new_dataset_number_and_destination_conflict(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证契约：L6/L12：最大编号变化或目的目录出现时整个写入冲突，不偷偷重分配编号。"""
    from creation_support import creation_api_case, preview_job, run_queued
    from navwrite_support import tree_state

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        for mutation in ("number", "destination"):
            identifier = preview_job(api, deps, fake_nav, operation="dataset")
            if mutation == "number":
                (deps.rescan.nav_root / "已移除/dataset-60_old").mkdir(parents=True)
            else:
                (deps.rescan.nav_root / "按任务/接口新数据集").mkdir()
            before = tree_state(deps.rescan.nav_root)
            submitted = api.client.post(
                "/api/datasets/creation-writes", json={"preview_job_id": identifier}
            )
            record = run_queued(api, deps, submitted.json()["job_id"])
            assert record.summary is not None and record.summary.aborted
            assert tree_state(deps.rescan.nav_root) == before


def test_shared_journal_rollback_recovery(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L13/L14：两种新计划均走已有日志先行/逆序回滚/重启恢复；故障不留下不明半成品且不改存储目标。"""
    from creation_support import creation_api_case, preview_job
    from navwrite_support import tree_state

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        import time

        from navwrite_support import noop

        from rdp.jobs.navwrite.atomic import apply_plan, capture_before_images
        from rdp.jobs.navwrite.journal import write_journal
        from rdp.jobs.navwrite.previews import read_preview
        from rdp.jobs.navwrite.recovery import RecoveryDependencies, recover_navigation_writes
        from rdp.jobs.types import JobClock

        for offset, operation in enumerate(("link", "dataset")):
            identifier = preview_job(api, deps, fake_nav, operation=operation)
            plan = read_preview(deps.paths, int(identifier)).plan
            before = tree_state(deps.rescan.nav_root)
            write_journal(
                deps.paths,
                plan,
                capture_before_images(deps.rescan.nav_root, plan),
                900 + offset,
                api.clock(),
            )
            partial = plan.model_copy(update={"steps": plan.steps[:3]})
            apply_plan(deps.rescan.nav_root, partial, 900 + offset, checkpoint=noop)
            result = recover_navigation_writes(
                RecoveryDependencies(
                    api.engine,
                    deps.paths,
                    deps.rescan.nav_root,
                    JobClock(api.clock, time.monotonic),
                ),
                checkpoint=noop,
            )
            assert not result.blocked and result.journals
            assert tree_state(deps.rescan.nav_root) == before


def test_apply_reindex_sizing_and_change_record(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L15/L16 与验收 1：成功后同作业更新索引、提交统计，记录操作摘要与永久变更记录，来源可查询。"""
    from creation_support import creation_api_case, preview_job, run_queued

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from rdp.jobs.navwrite.changes import read_change_record

        identifier = preview_job(
            api, deps, fake_nav, operation="dataset", format_entries=[{"format": "mcap"}]
        )
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert submitted.status_code == 201
        job_id = submitted.json()["job_id"]
        result = run_queued(api, deps, job_id)
        assert result.summary is not None and not result.summary.aborted
        record = read_change_record(deps.paths, int(job_id))
        assert record.outcome.value == "committed"
        items = api.client.get("/api/datasets").json()["items"]
        assert any(
            item["dataset_id"] == "dataset-36" and item["name"] == "接口新数据集" for item in items
        )
        jobs = api.client.get("/api/jobs").json()["items"]
        assert any(
            item["type_name"] == "dataset_sizing"
            and item["parameters"] == {"dataset_id": "dataset-36"}
            for item in jobs
        )
        assert (deps.paths.nav_changes / f"{job_id}.json.gz").exists()


def test_copy_drill_link_and_dataset_panel(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：验收 1 的自动替代：临时导航样本完成建链、场景一、预计 dataset-36 和格式副本，再扫描不新增需要处理；不读真实部署或挂载数据。"""
    import json

    from creation_support import creation_api_case, preview_job, run_queued

    with creation_api_case(tmp_path, fake_nav) as (api, deps):

        def required() -> set[str]:
            response = api.client.get("/api/datasets/panel")
            assert response.status_code == 200, response.text
            return {
                json.dumps(item, sort_keys=True)
                for item in response.json()["findings"]
                if item["severity"] == "action_required"
            }

        before = required()
        for operation in ("link", "dataset"):
            identifier = preview_job(
                api, deps, fake_nav, operation=operation, format_entries=[{"format": "mcap"}]
            )
            submitted = api.client.post(
                "/api/datasets/creation-writes", json={"preview_job_id": identifier}
            )
            assert submitted.status_code == 201, submitted.text
            result = run_queued(api, deps, submitted.json()["job_id"])
            assert result.summary is not None and not result.summary.aborted
        assert required() <= before
        assert (deps.rescan.nav_root / "按任务/接口新数据集/新增链接").is_symlink()
        assert (deps.rescan.nav_root / "按格式/mcap/接口新数据集/新增链接").is_symlink()
