"""调度HTTP边界测试；通过真实应用访问临时数据库，不探测硬件。"""

from pathlib import Path

import pytest


def test_authentication(tmp_path: Path) -> None:
    """契约：真实应用GET调度未登录401、强制改密403，普通成员与管理员均可200，鉴权先于查询。"""
    from account_api_support import add_actor
    from jobs_api_support import job_api_case
    from pydantic import SecretStr

    with job_api_case(tmp_path) as case:
        assert case.client.get("/api/worker/scheduling").status_code == 401
        assert case.login().status_code == 200
        assert case.client.get("/api/worker/scheduling").status_code == 200
        add_actor(case, name="forced", ready=False)
        case.client.cookies.clear()
        assert case.login("forced").status_code == 200
        assert case.client.get("/api/worker/scheduling").status_code == 403
        add_actor(case, name="member", ready=True)
        case.client.cookies.clear()
        assert case.login("member", SecretStr("member-updated-value")).status_code == 200
        assert case.client.get("/api/worker/scheduling").status_code == 200


def test_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：真实API只从数据库及入口catalog读取，不探测nvidia-smi、不读配置文件/worker内存/导航层。"""
    import ast
    import inspect
    import subprocess

    from jobs_api_support import job_api_case
    from sqlalchemy import event

    from rdp.jobs import scheduling_service

    imports = {
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(scheduling_service)))
        if isinstance(node, ast.ImportFrom)
    }
    assert not imports & {
        "rdp.jobs.resources",
        "rdp.jobs.scheduling",
        "rdp.jobs.execution",
        "rdp.jobs.navigation",
        "rdp.jobs.worker",
    }
    with job_api_case(tmp_path) as case:
        case.login()
        writes: list[str] = []

        def observe(*args: object) -> None:
            if isinstance(args[2], str) and args[2].startswith(
                (
                    "INSERT INTO jobs",
                    "UPDATE jobs",
                    "DELETE FROM jobs",
                    "INSERT INTO operation_logs",
                )
            ):
                writes.append(args[2])

        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("只读调度不能访问文件或外部工具")

        event.listen(case.engine, "before_cursor_execute", observe)
        try:
            with monkeypatch.context() as patch:
                patch.setattr(Path, "open", forbidden)
                patch.setattr(subprocess, "Popen", forbidden)
                response = case.client.get("/api/worker/scheduling")
                assert response.status_code == 200
            assert writes == []
        finally:
            event.remove(case.engine, "before_cursor_execute", observe)


def test_resource_snapshot(tmp_path: Path) -> None:
    """契约：类型上限和running/cancelling计数正确、终态GPU只作历史不占卡、写锁持有人正确，编号是文本。"""
    from dataclasses import replace

    from jobs_api_support import job_api_case
    from jobs_scheduling_support import catalog_fixture
    from jobs_storage_support import job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.registry import production_registry
    from rdp.jobs.types import JobState

    base = catalog_fixture(production_registry())
    settings = replace(
        base.settings,
        gpus=(0, 1),
        types=tuple(
            replace(item, concurrency=2) if item.type_name == "example_count" else item
            for item in base.settings.types
        ),
    )
    with job_api_case(tmp_path, catalog=replace(base, settings=settings)) as case:
        with session_scope(case.engine) as session:
            first = job_row(JobState.RUNNING, job_id=71)
            first.gpu_index, first.holds_navigation_lock = 0, True
            second = job_row(JobState.CANCELLING, job_id=72)
            ended = job_row(JobState.COMPLETED, job_id=73)
            ended.gpu_index = 1
            session.add_all((first, second, ended))
        case.login()
        response = case.client.get("/api/worker/scheduling")
        assert response.status_code == 200
        data = response.json()
        usage = next(item for item in data["types"] if item["type_name"] == "example_count")
        assert (usage["concurrency"], usage["running_count"]) == (2, 2)
        assert [(item["gpu_index"], item["job_id"]) for item in data["gpus"]] == [
            (0, "71"),
            (1, None),
        ]
        assert data["navigation_job_id"] == "71"


def test_schedule_snapshot(tmp_path: Path) -> None:
    """契约：每日下次UTC时刻、最近作业链接与六态/结果正确，未提交为null，不重算作业结果。"""
    from dataclasses import replace
    from datetime import UTC, datetime, time, timedelta

    from jobs_api_support import job_api_case
    from jobs_scheduling_support import catalog_fixture
    from jobs_storage_support import job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.registry import production_registry
    from rdp.jobs.schedule_records import insert_submission
    from rdp.jobs.schedules import production_schedules
    from rdp.jobs.scheduling_types import ScheduleSubmission
    from rdp.jobs.types import JobState

    registry = production_registry()
    catalog = replace(catalog_fixture(registry), schedules=production_schedules(registry))
    rule = catalog.schedules.definitions()[0]
    for state in JobState:
        with job_api_case(tmp_path / state.value, registry=registry, catalog=catalog) as case:
            now = case.clock.value
            with session_scope(case.engine) as session:
                row = job_row(state)
                row.type_name, row.parameters = rule.type_name, {}
                session.add(row)
                session.flush()
                insert_submission(session, ScheduleSubmission(rule.name, now.date(), 71, now))
            case.login()
            response = case.client.get("/api/worker/scheduling")
            assert response.status_code == 200
            plans = {item["name"]: item for item in response.json()["schedules"]}
            saved = plans[rule.name]
            assert saved["last_job_id"] == "71" and saved["last_state"] == state.value
            assert saved["last_outcome"] == (
                "partially_succeeded" if state is JobState.COMPLETED else None
            )
            assert datetime.fromisoformat(saved["next_run_at"]) == datetime.combine(
                now.date() + timedelta(days=1), time(3), UTC
            )
            missing = next(item for name, item in plans.items() if name != rule.name)
            assert (
                missing["last_job_id"] is missing["last_state"] is missing["last_outcome"] is None
            )


def test_offline_display(tmp_path: Path) -> None:
    """契约：离线worker返回False并保留最后占用副本，查询故障502不冒充空闲或离线。"""
    from datetime import timedelta

    from jobs_api_support import job_api_case
    from jobs_storage_support import job_row
    from sqlalchemy import event

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.records import save_heartbeat
    from rdp.jobs.types import WorkerHeartbeat

    with job_api_case(tmp_path) as case:
        now = case.clock.value
        with session_scope(case.engine) as session:
            row = job_row()
            row.holds_navigation_lock = True
            session.add(row)
            save_heartbeat(
                session, WorkerHeartbeat("00000000000040008000000000000001", 123, now, now)
            )
        case.login()
        assert case.client.get("/api/worker/scheduling").json()["worker_online"] is True
        case.clock.value += timedelta(seconds=16)
        response = case.client.get("/api/worker/scheduling")
        assert response.status_code == 200 and response.json()["worker_online"] is False
        assert response.json()["navigation_job_id"] == "71"

        def fail(*args: object) -> None:
            if isinstance(args[2], str) and "FROM worker_heartbeat" in args[2]:
                raise OSError("模拟心跳读取失败")

        event.listen(case.engine, "before_cursor_execute", fail)
        try:
            assert case.client.get("/api/worker/scheduling").status_code == 502
        finally:
            event.remove(case.engine, "before_cursor_execute", fail)


def test_system_response(tmp_path: Path) -> None:
    """契约：系统提交人account_id为JSON null而非字符串None，名字系统、deleted=False。"""
    from jobs_api_support import job_api_case

    from rdp.jobs.registry import production_registry
    from rdp.jobs.scheduling_types import ScheduledJob
    from rdp.jobs.service import JobService

    with job_api_case(tmp_path) as case:
        service = JobService(case.engine, production_registry())
        submission = service.submit_scheduled(
            ScheduledJob("清除", "purge_errors", {}, description="删除超过保留期的程序报错记录"),
            case.clock.value.date(),
            now=case.clock.value,
        )
        assert submission is not None
        case.login()
        response = case.client.get(f"/api/jobs/{submission.job_id}")
        assert response.status_code == 200
        assert response.json()["submitted_by"] == {
            "account_id": None,
            "name": "系统",
            "deleted": False,
        }


def test_job_waiting(tmp_path: Path) -> None:
    """契约：列表/详情包含等待原因和卡号，等待不改变state；终态等待/持锁清空但卡号保留。"""
    from jobs_api_support import job_api_case
    from jobs_storage_support import job_row

    from rdp.infra.db.connection import session_scope
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    with job_api_case(tmp_path) as case:
        with session_scope(case.engine) as session:
            queued = job_row(JobState.QUEUED, job_id=71)
            queued.wait_reason = "gpu"
            running = job_row(JobState.RUNNING, job_id=72)
            running.wait_reason, running.gpu_index = "navigation_lock", 1
            session.add_all((queued, running))
        case.login()
        items = {item["job_id"]: item for item in case.client.get("/api/jobs").json()["items"]}
        assert items["71"]["wait_reason"] == "gpu" and items["71"]["state"] == "queued"
        detail = case.client.get("/api/jobs/72").json()
        assert (detail["state"], detail["wait_reason"], detail["gpu_index"]) == (
            "running",
            "navigation_lock",
            1,
        )
        with session_scope(case.engine) as session:
            transition_job(
                session, 72, StateChange(JobState.RUNNING, JobState.COMPLETED, case.clock.value)
            )
        ended = case.client.get("/api/jobs/72").json()
        assert (
            ended["wait_reason"] is None
            and not ended["holds_navigation_lock"]
            and ended["gpu_index"] == 1
        )


def test_example_payloads(tmp_path: Path) -> None:
    """契约：真实示例提交端点的时长bool/超界/额外字段/路径为安全422，合法参数201且写当前账号审计。"""
    from jobs_api_support import job_api_case
    from sqlalchemy import select

    from rdp.audit.models import OperationLogRow
    from rdp.infra.db.connection import session_scope

    with job_api_case(tmp_path) as case:
        case.login()
        invalid = (
            ("gpu", {"hold_s": True}),
            ("gpu", {"hold_s": 601}),
            ("gpu", {"hold_s": 0, "path": "拒绝回显的路径"}),
            ("navigation", {"expected_value": "", "pause_s": True}),
            ("navigation", {"expected_value": "", "pause_s": 11}),
            ("navigation", {"expected_value": "x" * 257}),
            ("navigation", {"expected_value": "", "path": "拒绝回显的路径"}),
        )
        for name, body in invalid:
            response = case.client.post("/api/jobs/example/" + name, json=body)
            assert response.status_code == 422 and "拒绝回显的路径" not in response.text
        for name, body in (
            ("gpu", {"hold_s": 0}),
            ("navigation", {"expected_value": "", "pause_s": 0}),
        ):
            response = case.client.post("/api/jobs/example/" + name, json=body)
            assert response.status_code == 201
            job = response.json()
            assert job["state"] == "queued" and job["submitted_by"]["account_id"] is not None
            with session_scope(case.engine, read_only=True) as session:
                row = session.scalar(
                    select(OperationLogRow).where(
                        OperationLogRow.operation == "submit_job",
                        OperationLogRow.object_id == job["job_id"],
                    )
                )
                assert row is not None and str(row.actor_id) == job["submitted_by"]["account_id"]


def test_missing_configuration(tmp_path: Path) -> None:
    """契约：未装配调度服务时新接口502，原接口仍正常；configure_jobs必须显式提供catalog，不在请求内找默认配置。"""
    import inspect

    from jobs_api_support import job_api_case

    from rdp.api.jobs import configure_jobs

    parameter = inspect.signature(configure_jobs).parameters["scheduling"]
    assert (
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and parameter.default is inspect.Parameter.empty
    )
    with job_api_case(tmp_path) as case:
        case.login()
        case.app.state.scheduling_service = None
        response = case.client.get("/api/worker/scheduling")
        assert response.status_code == 502 and response.headers["content-type"].startswith(
            "application/problem+json"
        )
        assert case.client.get("/api/jobs").status_code == 200
    from dataclasses import replace
    from typing import cast
    from zoneinfo import ZoneInfo

    from jobs_scheduling_support import catalog_fixture

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.registry import production_registry
    from rdp.jobs.schedules import production_schedules

    registry = production_registry()
    catalog = catalog_fixture(registry)
    with pytest.raises(DefectError):
        replace(catalog, timezone=cast(ZoneInfo, None))
    with pytest.raises(DefectError):
        replace(
            catalog,
            settings=replace(
                catalog.settings, types=(replace(catalog.settings.types[0], concurrency=0),)
            ),
        )
    with pytest.raises(DefectError):
        replace(
            catalog,
            schedules=production_schedules(registry),
            settings=replace(catalog.settings, types=()),
        )


def test_inconsistent_display(tmp_path: Path) -> None:
    """契约：数据库双持锁/双卡主是DefectError而非随机选一条，统一错误编号响应。"""
    from jobs_api_support import job_api_case
    from jobs_storage_support import job_row

    from rdp.infra.db.connection import session_scope

    for field in ("holds_navigation_lock", "gpu_index"):
        with job_api_case(tmp_path / field) as case:
            with session_scope(case.engine) as session:
                first, second = job_row(job_id=71), job_row(job_id=72)
                setattr(first, field, True if field == "holds_navigation_lock" else 0)
                setattr(second, field, True if field == "holds_navigation_lock" else 0)
                session.add_all((first, second))
            case.login()
            response = case.client.get("/api/worker/scheduling")
            assert response.status_code == 500
            assert response.json()["error_id"] == response.headers["X-Request-ID"]
            assert "Traceback" not in response.text


def test_system_reserved_account(tmp_path: Path) -> None:
    """契约：显示名系统的正编号账号照常提交/重提并按编号显示；只有空编号是固定系统身份，OPS_ACTOR不能提交。"""
    from jobs_api_support import job_api_case
    from sqlalchemy import select

    from rdp.accounts.models import AccountRow
    from rdp.infra.actors import OPS_ACTOR
    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.records import NewJob, insert_job
    from rdp.jobs.registry import production_registry

    with job_api_case(tmp_path) as case:
        with session_scope(case.engine) as session:
            account = session.scalar(select(AccountRow))
            assert account is not None
            account.display_name = "系统"
            account_id = account.account_id
        case.login()
        response = case.client.post("/api/jobs/example", json={"steps": 1, "interval_ms": 0})
        assert response.status_code == 201
        saved = response.json()
        assert saved["submitted_by"] == {
            "account_id": str(account_id),
            "name": "系统",
            "deleted": False,
        }
        case.client.post(f"/api/jobs/{saved['job_id']}/cancel")
        child = case.client.post(f"/api/jobs/{saved['job_id']}/resubmit")
        assert child.status_code == 201 and child.json()["submitted_by"] == saved["submitted_by"]
        definition = production_registry().lookup("example_count")
        assert definition is not None
        with pytest.raises(DefectError), session_scope(case.engine) as session:
            insert_job(
                session,
                NewJob(
                    definition, {"steps": 1, "interval_ms": 0}, OPS_ACTOR, case.clock.value, None
                ),
            )


def test_excluded_gpus_visible_without_hardware_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约：真实调度GET展示被移出的卡、诊断和核对时刻；未知实例显示unknown，Web不调用核卡或资源池。"""
    import subprocess
    from dataclasses import replace
    from datetime import datetime

    from jobs_api_support import job_api_case
    from jobs_progress_support import diagnostic
    from jobs_scheduling_support import catalog_fixture

    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import DiagnosticCategory, DiagnosticLevel
    from rdp.jobs.records import save_heartbeat
    from rdp.jobs.registry import production_registry
    from rdp.jobs.resources import save_gpu_checks
    from rdp.jobs.scheduling_types import GpuCheck
    from rdp.jobs.types import WorkerHeartbeat

    base = catalog_fixture(production_registry())
    catalog = replace(base, settings=replace(base.settings, gpus=(0, 1)))
    instance = "00000000000040008000000000000001"
    error = diagnostic(1).model_copy(
        update={"category": DiagnosticCategory.EXTERNAL, "level": DiagnosticLevel.ERROR}
    )
    with job_api_case(tmp_path, catalog=catalog) as case:
        case.login()
        now = case.clock.value
        with session_scope(case.engine) as session:
            save_gpu_checks(
                session, instance, (GpuCheck(0, True, (), now), GpuCheck(1, False, (error,), now))
            )
            save_heartbeat(session, WorkerHeartbeat(instance, 123, now, now))

        def forbidden(*args: object, **kwargs: object) -> None:
            raise AssertionError("Web不能探测硬件")

        monkeypatch.setattr(subprocess, "Popen", forbidden)
        response = case.client.get("/api/worker/scheduling")
        assert response.status_code == 200
        cards = response.json()["gpus"]
        assert [card["availability"] for card in cards] == ["available", "excluded"]
        assert cards[1]["job_id"] is None and cards[1]["diagnostics"] == [
            error.model_dump(mode="json")
        ]
        assert datetime.fromisoformat(cards[1]["checked_at"]) == now
        with session_scope(case.engine) as session:
            save_heartbeat(
                session, WorkerHeartbeat("00000000000040008000000000000002", 124, now, now)
            )
        unknown = case.client.get("/api/worker/scheduling").json()["gpus"]
        assert all(
            card["availability"] == "unknown"
            and card["checked_at"] is None
            and card["diagnostics"] == []
            for card in unknown
        )
