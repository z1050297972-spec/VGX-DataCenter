"""M1-08 契约行为清单；只使用临时目录或 tests 假导航，真实副本演练由执行线负责。"""

from pathlib import Path

import pytest
from nav_manifest import FakeNavigation


def test_routes_and_generated_contract() -> None:
    """验证契约：HTTP 契约：五个新增路径方法、请求字段、响应及 SessionCookie 出现在真实应用 OpenAPI，类型由 make api-types 生成。"""
    from rdp.api import create_app

    schema = create_app(None, database=None).openapi()
    for path, method in (
        ("creation-options", "get"),
        ("link-previews", "post"),
        ("creation-previews", "post"),
        ("creation-previews/{preview_job_id}", "get"),
        ("creation-writes", "post"),
    ):
        operation = schema["paths"]["/api/datasets/" + path][method]
        assert operation["security"] == [{"SessionCookie": []}]
    confirm = schema["paths"]["/api/datasets/creation-writes"]["post"]
    assert "201" in confirm["responses"] and "200" not in confirm["responses"]
    assert "CreationSubmitResponse" not in schema["components"]["schemas"]


def test_origin_auth_password_member(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：安全边界：真实应用先 Origin、认证、强制改密；成员与管理员都可创建，额外字段/非法模型统一 422 且不回显输入。"""
    from creation_support import creation_api_case

    with creation_api_case(tmp_path, fake_nav) as (api, _deps):
        from account_api_support import add_actor
        from pydantic import SecretStr

        assert (
            api.client.post(
                "/api/datasets/creation-writes", headers={"Origin": ""}, json={}
            ).status_code
            == 403
        )
        api.client.cookies.clear()
        assert api.client.get("/api/datasets/creation-options").status_code == 401
        assert api.login().status_code == 200
        add_actor(api, ready=False)
        assert api.login("member").status_code == 200
        assert api.client.get("/api/datasets/creation-options").status_code == 403
        # 使用既有领域夹具完成改密，再经真实登录与业务接口核验成员权限。
        api.client.cookies.clear()
        assert api.login().status_code == 200
        add_actor(api, name="ready_member")
        assert api.login("ready_member", SecretStr("member-updated-value")).status_code == 200
        assert api.client.get("/api/datasets/creation-options").status_code == 200


def test_web_cannot_access_targets(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：ADR 0006：把临时存储根设为不可读，HTTP 仍只提交预览行，不 stat/resolve/open 目标或执行 builder。"""
    from creation_support import creation_api_case
    from navwrite_support import dataset_id_of

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        import os
        from pathlib import Path

        original = Path.stat

        def forbid(path: Path, *, follow_symlinks: bool = True) -> os.stat_result:
            if any(path.is_relative_to(root.path) for root in deps.rescan.roots):
                raise AssertionError("Web访问存储目标")
            return original(path, follow_symlinks=follow_symlinks)

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(Path, "stat", forbid)
            response = api.client.post(
                "/api/datasets/link-previews",
                json={
                    "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
                    "link": {
                        "name": "x",
                        "target_path": str(deps.rescan.roots[0].path / "never-created"),
                        "fallback_format": "mcap",
                    },
                },
            )
        assert response.status_code == 201, response.text
        assert response.json()["state"] == "queued"


def test_submit_preview_job_types(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：建链与新建分别提交两个 RESTART 只读类型，返回 201 queued，当前账号和提交日志同事务。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from rdp.jobs.navwrite.create_jobs import build_creation_definitions

        for operation, kind in (
            ("link", "nav_create_link_preview"),
            ("dataset", "nav_create_dataset_preview"),
        ):
            identifier = preview_job(api, deps, fake_nav, operation=operation, execute=False)
            body = api.client.get(f"/api/jobs/{identifier}").json()
            assert body["type_name"] == kind and body["state"] == "queued"
            assert body["submitted_by"]["name"] == "管理员"
        for definition in build_creation_definitions(None):
            assert definition.recovery_mode.value == "restart" and not definition.writes_navigation


def test_preview_options_registry(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：候选来自格式/来源单一登记及索引版本，空索引仍有登记选项，读取不创建目录。"""
    from creation_support import creation_api_case

    with creation_api_case(tmp_path, fake_nav) as (api, _deps):
        response = api.client.get("/api/datasets/creation-options")
        assert response.status_code == 200, response.text
        value = response.json()
        assert [(item["format"], item["has_versions"]) for item in value["formats"]] == [
            ("lerobot", True),
            ("mcap", False),
            ("archives", False),
        ]
        assert value["formats"][2]["directory"] == "tar、tar.gz（含分卷）"
        assert value["data_origins"] == [
            "真机采集",
            "UMI 采集",
            "ego 采集",
            "仿真生成",
            "开源下载",
            "未知",
        ]


def test_read_only_successful_creation_preview(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：只有 completed 且 succeeded/succeeded_with_warnings 的正确创建预览可读/确认；运行、失败、取消、中断、错类型都拒绝。"""
    from creation_support import creation_api_case, preview_job, run_queued

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        pending = preview_job(api, deps, fake_nav, execute=False)
        assert api.client.get(f"/api/datasets/creation-previews/{pending}").status_code == 400
        api.client.post(f"/api/jobs/{pending}/cancel")
        assert api.client.get(f"/api/datasets/creation-previews/{pending}").status_code == 400
        failed = preview_job(
            api,
            deps,
            fake_nav,
            execute=False,
            link={
                "name": "x",
                "target_path": str(deps.rescan.roots[0].path / "missing"),
                "fallback_format": "mcap",
            },
        )
        record = run_queued(api, deps, failed)
        assert record.summary is not None and record.summary.aborted
        assert api.client.get(f"/api/datasets/creation-previews/{failed}").status_code == 400
        success = preview_job(api, deps, fake_nav)
        assert api.client.get(f"/api/datasets/creation-previews/{success}").status_code == 200
        assert api.client.get("/api/datasets/creation-previews/71").status_code == 400


def test_preview_missing_corrupt_expired(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：不存在作业 404；丢失/损坏/七天过期文件给输入诊断；文件 I/O 失败给外部失败，不伪造空预览。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from datetime import timedelta

        assert api.client.get("/api/datasets/creation-previews/999999").status_code == 404
        missing = preview_job(api, deps, fake_nav)
        (deps.paths.nav_previews / f"{missing}.json.gz").unlink()
        assert api.client.get(f"/api/datasets/creation-previews/{missing}").status_code == 400
        corrupt = preview_job(api, deps, fake_nav)
        (deps.paths.nav_previews / f"{corrupt}.json.gz").write_bytes(b"bad")
        assert api.client.get(f"/api/datasets/creation-previews/{corrupt}").status_code == 400
        expired = preview_job(api, deps, fake_nav)
        api.clock.value += timedelta(days=8)
        assert api.login().status_code == 200
        assert api.client.get(f"/api/datasets/creation-previews/{expired}").status_code == 400


def test_preview_response_excludes_plan_body(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：结果只有身份、参数、报告差异及排队提醒，不暴露 after_content 或接受客户端 plan。"""
    from creation_support import creation_api_case, preview_job
    from navwrite_support import tree_state

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        identifier = preview_job(api, deps, fake_nav)
        before = tree_state(deps.rescan.nav_root)
        response = api.client.get(f"/api/datasets/creation-previews/{identifier}")
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["operation"] == "create_link" and value["report"]["creation"]["sources_added"]
        assert "plan" not in value and "after_content" not in response.text
        assert tree_state(deps.rescan.nav_root) == before


def test_confirm_only_references_saved_plan(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：确认只传预览与已见队列编号，提交 NAV_APPLY_TYPE 参数仅 preview_job_id，执行复用同一持久计划。"""
    from creation_support import creation_api_case, run_queued

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        target = deps.rescan.roots[0].path / "api-target"
        target.mkdir()
        response = api.client.post(
            "/api/datasets/creation-previews",
            json={
                "dataset_name": "接口新数据集",
                "data_origin": "开源下载",
                "link": {"name": "原始数据", "target_path": str(target), "fallback_format": "mcap"},
                "format_entries": [{"format": "mcap"}],
            },
        )
        assert response.status_code == 201, response.text
        preview_id = response.json()["job_id"]
        record = run_queued(api, deps, preview_id)
        assert record.summary is not None and not record.summary.aborted
        view = api.client.get(f"/api/datasets/creation-previews/{preview_id}")
        assert view.status_code == 200, view.text
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": preview_id}
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["type_name"] == "nav_write_apply"
        assert submitted.json()["parameters"] == {"preview_job_id": int(preview_id)}
        result = run_queued(api, deps, submitted.json()["job_id"])
        assert result.summary is not None and not result.summary.aborted
        assert (deps.rescan.nav_root / "按任务/接口新数据集/原始数据").is_symlink()


def test_queued_write_warning_requires_ack(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：ADR 0005：同数据集未确认的排队写作业先返回409五段诊断且不插作业；确认所见编号后返回201，新编号出现再次提醒。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        identifier = preview_job(api, deps, fake_nav)
        first = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert first.status_code == 201, first.text
        job_id = first.json()["job_id"]
        before = api.client.get("/api/jobs").json()["items"]
        second = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert second.status_code == 409, second.text
        diagnostics = second.json()["diagnostics"]
        assert diagnostics[0]["rule"] == "NAV_CREATE_QUEUE_CONFIRMATION"
        assert any(
            item["value"] == job_id for diagnostic in diagnostics for item in diagnostic["objects"]
        )
        assert len(api.client.get("/api/jobs").json()["items"]) == len(before)
        ack = api.client.post(
            "/api/datasets/creation-writes",
            json={"preview_job_id": identifier, "acknowledged_queue_job_ids": [job_id]},
        )
        assert ack.status_code == 201 and ack.json()["job_id"] != job_id
        again = api.client.post(
            "/api/datasets/creation-writes",
            json={"preview_job_id": identifier, "acknowledged_queue_job_ids": [job_id]},
        )
        assert again.status_code == 409


def test_queue_resolves_plan_dataset_ids(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：nav_write_apply 参数只有预览编号时仍通过保存计划找同编号；排除只读预览、其他数据集和非排队作业。"""
    from creation_support import creation_api_case, preview_job
    from navwrite_support import dataset_id_of

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        first = preview_job(api, deps, fake_nav)
        second = preview_job(api, deps, fake_nav)
        queued = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": first}
        ).json()["job_id"]
        assert (
            api.client.post(
                "/api/datasets/creation-writes", json={"preview_job_id": second}
            ).status_code
            == 409
        )
        other = preview_job(
            api, deps, fake_nav, dataset_id=dataset_id_of(fake_nav, "agibot_world_alpha")
        )
        assert (
            api.client.post(
                "/api/datasets/creation-writes", json={"preview_job_id": other}
            ).status_code
            == 201
        )
        api.client.post(f"/api/jobs/{queued}/cancel")
        view = api.client.get(f"/api/datasets/creation-previews/{second}").json()
        assert view["queued_jobs"] == []


def test_identifier_precision_and_oversize(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：作业编号全程文本支持 2^63-1，拒绝前导零/负数/超范围和重复确认编号，不经过浮点转换。"""
    from creation_support import creation_api_case, preview_job
    from navwrite_support import dataset_id_of

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        identifier = preview_job(api, deps, fake_nav)
        assert (
            api.client.get("/api/datasets/creation-previews/9223372036854775807").status_code == 404
        )
        for value in ("01", "-1", "9223372036854775808"):
            assert api.client.get(f"/api/datasets/creation-previews/{value}").status_code == 422
        assert (
            api.client.post(
                "/api/datasets/creation-writes",
                json={"preview_job_id": identifier, "acknowledged_queue_job_ids": ["1", "1"]},
            ).status_code
            == 422
        )
        # M1.5-13统一放宽为1 MiB；仍须在入队前拒绝超过整份参数预算的请求。
        oversized = api.client.post(
            "/api/datasets/link-previews",
            json={
                "dataset_id": dataset_id_of(fake_nav, "EgoProDemo"),
                "link": {
                    "name": "x",
                    "target_path": "/" + "x" * (1024 * 1024),
                    "fallback_format": "mcap",
                },
            },
        )
        assert oversized.status_code == 422


def test_submitter_and_storage_failures(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：契约：确认者是写入提交人，审计 IP/请求编号必填；队列或日志事务失败不留半条作业。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        import sqlite3

        from account_api_support import add_actor
        from pydantic import SecretStr
        from sqlalchemy import event

        identifier = preview_job(api, deps, fake_nav)
        # 专用确认已核验保存的预览，成员仍可确认；通用提交另受 D2 角色限制。
        add_actor(api)
        assert api.login("member", SecretStr("member-updated-value")).status_code == 200
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert submitted.status_code == 201, submitted.text
        assert (
            submitted.json()["submitted_by"]["account_id"]
            == api.client.get("/api/auth/me").json()["account_id"]
        )

        def fail_insert(*args: object) -> None:
            statement = args[2]
            if isinstance(statement, str) and statement.upper().startswith("INSERT INTO JOBS"):
                error = sqlite3.OperationalError("disk I/O error")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error

        event.listen(api.engine, "before_cursor_execute", fail_insert)
        try:
            response = api.client.post(
                "/api/datasets/creation-previews",
                json={
                    "dataset_name": "故障",
                    "data_origin": "未知",
                    "link": {"name": "x", "target_path": "/unused", "fallback_format": "mcap"},
                },
            )
            assert response.status_code == 502, response.text
        finally:
            event.remove(api.engine, "before_cursor_execute", fail_insert)


def test_preview_cancellation_restart(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：作业契约：预览取消不留半份结果，worker RESTART 从头生成；缺依赖/错模式为程序缺陷。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from rdp.jobs.navwrite.create_jobs import build_creation_definitions

        identifier = preview_job(api, deps, fake_nav, execute=False)
        response = api.client.post(f"/api/jobs/{identifier}/cancel")
        assert response.status_code in (200, 204), response.text
        assert api.client.get(f"/api/jobs/{identifier}").json()["state"] == "cancelled"
        assert not (deps.paths.nav_previews / f"{identifier}.json.gz").exists()
        assert all(
            item.recovery_mode.value == "restart" for item in build_creation_definitions(deps)
        )


def test_confirmation_after_recovery_block(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证契约：L14：恢复失败时仍能提交排队，既有门禁阻止 nav_write_apply 领取，预览不写导航。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from rdp.infra.db.connection import session_scope
        from rdp.jobs.navwrite.marker import record_recovery_block
        from rdp.jobs.navwrite.models import MismatchItem

        identifier = preview_job(api, deps, fake_nav)
        with session_scope(api.engine) as session:
            record_recovery_block(
                session,
                (
                    MismatchItem(
                        job_id=999,
                        step_index=0,
                        path="fake",
                        expected_before="a",
                        expected_after="b",
                        actual="c",
                    ),
                ),
                now=api.clock(),
            )
        assert api.client.get("/api/navigation/recovery-block").json()["blocked"]
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.json()["state"] == "queued"


def test_optional_creation_report_preserves_history(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证契约：旧 PlanReport 不含 creation 时读为 None；新字段随原有预览与变更记录格式保存，不改变其他操作的含义。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from navwrite_pipeline_support import EMPTY_REPORT

        from rdp.jobs.navwrite.models import PlanReport

        legacy = EMPTY_REPORT.model_dump(exclude={"creation"})
        assert PlanReport.model_validate(legacy).creation is None
        identifier = preview_job(api, deps, fake_nav)
        assert (
            api.client.get(f"/api/datasets/creation-previews/{identifier}").json()["report"][
                "creation"
            ]
            is not None
        )


def test_creation_response_rejects_inconsistent_branches(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证契约：确认成功返回201完整作业，取消可空作业分支；创建预览操作匹配参数且noop必须零差异。"""
    from creation_support import creation_api_case, preview_job

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        from pydantic import ValidationError

        from rdp.jobs.navwrite.create_views import CreationPreviewView

        identifier = preview_job(api, deps, fake_nav)
        body = api.client.get(f"/api/datasets/creation-previews/{identifier}").json()
        body["report"]["creation"]["noop"] = True
        with pytest.raises(ValidationError):
            CreationPreviewView.model_validate(body)
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert submitted.status_code == 201 and "job_id" in submitted.json()
        assert "job" not in submitted.json() and "confirmation_required" not in submitted.json()


def test_create_information_preview_and_write(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证09号契约：文字与分类写入两视图，未填项留空，不传FPS不写顶层键。"""
    import json

    from creation_support import creation_api_case, preview_job, run_queued

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        identifier = preview_job(
            api,
            deps,
            fake_nav,
            operation="dataset",
            format_entries=[{"format": "mcap"}],
            information={
                "fields": [
                    {"number": 6, "value_markdown": "**桌面收纳**"},
                    {"number": 5, "value_markdown": "双臂机器人"},
                ],
                "robot_model": "R1 Lite",
                "scene": [" 家居 ", "tabletop", "家居"],
                "tasks": [" 收纳 ", "抓取", "收纳"],
            },
        )
        response = api.client.get(f"/api/datasets/creation-previews/{identifier}")
        assert response.status_code == 200, response.text
        changes = {
            item["json_path"]: json.loads(item["after"])
            for item in response.json()["report"]["listed_changes"]
            if item["file"] == "按任务/接口新数据集/数据集信息.json"
        }
        assert changes["fields/4/value_markdown"] == "双臂机器人"
        assert changes["fields/5/value_markdown"] == "**桌面收纳**"
        assert changes["robot_model"] == "R1 Lite"
        assert changes["scene"] == ["家居", "tabletop"]
        assert changes["tasks"] == ["收纳", "抓取"]
        submitted = api.client.post(
            "/api/datasets/creation-writes", json={"preview_job_id": identifier}
        )
        assert submitted.status_code == 201, submitted.text
        result = run_queued(api, deps, submitted.json()["job_id"])
        assert result.summary is not None and not result.summary.aborted
        canonical = deps.rescan.nav_root / "按任务/接口新数据集/数据集信息.json"
        replica = deps.rescan.nav_root / "按格式/mcap/接口新数据集/数据集信息.json"
        assert canonical.read_bytes() == replica.read_bytes()
        info = json.loads(canonical.read_text())
        assert info["fields"][4]["value_markdown"] == "双臂机器人"
        assert info["fields"][5]["value_markdown"] == "**桌面收纳**"
        assert all(
            field["value_markdown"] == ""
            for field in info["fields"]
            if field["number"] not in (5, 6)
        )
        assert info["robot_model"] == "R1 Lite"
        assert info["scene"] == ["家居", "tabletop"]
        assert info["tasks"] == ["收纳", "抓取"]
        assert "fps" not in info


@pytest.mark.parametrize(
    "information",
    [
        {"fields": [{"number": 4, "value_markdown": "正文"}]},
        {"fields": [{"number": 5, "value_markdown": "正文"}] * 2},
        {"scene": ["unlabeled"]},
    ],
)
def test_create_information_rejects_numbers(
    tmp_path: Path, fake_nav: FakeNavigation, information: dict[str, object]
) -> None:
    """验证09号契约：第4项和重复编号在提交预览时返回422，不进入worker。"""
    from creation_support import creation_api_case

    with creation_api_case(tmp_path, fake_nav) as (api, deps):
        response = api.client.post(
            "/api/datasets/creation-previews",
            json={
                "dataset_name": "非法信息",
                "data_origin": "开源下载",
                "link": {
                    "name": "原始数据",
                    "target_path": str(deps.rescan.roots[0].path / "unused"),
                    "fallback_format": "mcap",
                },
                "information": information,
            },
        )
        assert response.status_code == 422, response.text
