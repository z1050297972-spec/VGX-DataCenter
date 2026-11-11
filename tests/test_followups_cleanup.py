"""遗留整理的关键行为验收；只用临时数据库和真实 ASGI，不访问部署环境。"""

import logging
from datetime import timedelta
from pathlib import Path
from threading import Event, Lock

import anyio
import httpx
import pytest
from account_api_support import ApiCase, add_actor
from accounts_support import EXAMPLE_SECRET
from jobs_api_support import job_api_case
from nav_manifest import FakeNavigation
from pydantic import SecretStr
from sqlalchemy import func, select

from rdp.accounts.policy import ARGON2_MAX_CONCURRENCY
from rdp.accounts.security import PasswordCheck, PasswordCodec
from rdp.accounts.types import Role
from rdp.api import accounts
from rdp.audit.models import LoginLogRow
from rdp.infra.db.connection import session_scope
from rdp.jobs.models import JobRow
from rdp.jobs.registry import production_registry


def test_removed_backfill_cannot_be_submitted(tmp_path: Path) -> None:
    """验证回填专用接口已移除，通用提交拒绝旧类型且不创建作业。"""
    with job_api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.post("/api/navigation/backfill/preview", json={})
        assert response.status_code == 404, response.text
        response = case.client.post(
            "/api/jobs",
            json={"type_name": "nav_information_backfill_preview", "parameters": {}},
        )
        assert response.status_code == 422, response.text
        with session_scope(case.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(JobRow)) == 0


def test_production_submission_roles_and_member_write_rejection(tmp_path: Path) -> None:
    """验证27个生产类型的角色及集合精确匹配，成员不能经通用接口提交写入作业或留下记录。"""
    # 期望来自工单D2及已交付的归类表，不能从类型属性推导，否则降权变异会一起改变期望。
    expected_roles = {
        "conversion_ingest_apply": Role.ADMINISTRATOR,
        "conversion_ingest_preview": Role.MEMBER,
        "conversion_staging_delete": Role.ADMINISTRATOR,
        "dataset_rescan": Role.MEMBER,
        "dataset_sizing": Role.MEMBER,
        "download": Role.MEMBER,
        "download_ingest_apply": Role.ADMINISTRATOR,
        "download_ingest_preview": Role.MEMBER,
        "download_preview": Role.MEMBER,
        "download_staging_delete": Role.ADMINISTRATOR,
        "download_staging_scan": Role.MEMBER,
        "example_count": Role.MEMBER,
        "example_gpu": Role.ADMINISTRATOR,
        "example_navigation": Role.ADMINISTRATOR,
        "nav_classification_remove_preview": Role.MEMBER,
        "nav_create_dataset_preview": Role.MEMBER,
        "nav_create_link_preview": Role.MEMBER,
        "nav_fields_preview": Role.MEMBER,
        "nav_lineage_preview": Role.MEMBER,
        "nav_size_sync": Role.ADMINISTRATOR,
        "nav_repoint_preview": Role.MEMBER,
        "nav_write_apply": Role.ADMINISTRATOR,
        "purge_audit_logs": Role.ADMINISTRATOR,
        "purge_errors": Role.ADMINISTRATOR,
        "robot_connection_check": Role.MEMBER,
        "robot_preview_start": Role.MEMBER,
        "robot_preview_stop": Role.MEMBER,
    }
    actual_roles = {
        definition.type_name: definition.submission_role
        for definition in production_registry().definitions()
    }
    # 字典整体相等同时约束类型集合与各类型角色，多登记、漏登记和降权都会失败。
    assert actual_roles == expected_roles

    with job_api_case(tmp_path) as case:
        member = add_actor(case)
        response = case.client.post(
            "/api/jobs",
            headers={"Cookie": "rdp_session=" + member.token.get_secret_value()},
            json={"type_name": "nav_write_apply", "parameters": {"preview_job_id": 1}},
        )
        assert response.status_code == 403, response.text
        # 入库确认只由专用接口接受；通用提交仍执行 D2 的管理员角色声明。
        denied = case.client.post(
            "/api/jobs",
            headers={"Cookie": "rdp_session=" + member.token.get_secret_value()},
            json={"type_name": "download_ingest_apply", "parameters": {"preview_job_id": 1}},
        )
        assert denied.status_code == 403, denied.text
        with session_scope(case.engine, read_only=True) as session:
            assert session.scalar(select(func.count()).select_from(JobRow)) == 0


def test_member_confirms_ingest_via_dedicated_route(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """验证成员通过专用接口确认真实入库预览，提交人与读取结果保持当前成员身份。"""
    from download_ingest_support import PREVIEW_ID, build, ingest_case, save

    from rdp.jobs.navwrite.previews import read_preview, write_preview

    with ingest_case(tmp_path / "worker", fake_nav) as (harness, _stage):
        save(harness, build(harness))
        preview = read_preview(harness.case.paths, PREVIEW_ID)
        with session_scope(harness.case.engine, read_only=True) as session:
            row = session.get(JobRow, PREVIEW_ID)
            assert row is not None
            session.expunge(row)
        with job_api_case(tmp_path / "web") as case:
            # 使用真实 worker 产出的预览和临时作业快照，不替换授权或预览读取逻辑。
            with session_scope(case.engine) as session:
                session.merge(row)
            write_preview(case.app.state.job_paths, preview)
            member = add_actor(case)
            headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
            response = case.client.post(
                "/api/jobs/download-ingest",
                headers=headers,
                json={"preview_job_id": str(PREVIEW_ID)},
            )
            assert response.status_code == 201, response.text
            result = response.json()
            assert result["type_name"] == "download_ingest_apply"
            assert result["submitted_by"]["account_id"] == str(member.identity.account.account_id)
            fetched = case.client.get(f"/api/jobs/{result['job_id']}", headers=headers)
            assert fetched.status_code == 200, fetched.text
            assert fetched.json()["parameters"] == {"preview_job_id": PREVIEW_ID}


def test_submission_roles_before_parameters(tmp_path: Path) -> None:
    """验证成员提交清除类型先返回五段403，只读扫描仍可受理。"""
    with job_api_case(tmp_path) as case:
        member = add_actor(case)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        for parameters in ({"invalid": True}, list[object]()):
            denied = case.client.post(
                "/api/jobs",
                headers=headers,
                json={"type_name": "purge_errors", "parameters": parameters},
            )
            assert denied.status_code == 403
            assert denied.json()["diagnostics"]
        assert (
            case.client.post(
                "/api/jobs/example/gpu",
                content="{bad",
                headers=headers,
            ).status_code
            == 403
        )
        accepted = case.client.post(
            "/api/jobs",
            headers=headers,
            json={"type_name": "dataset_rescan", "parameters": {}},
        )
        assert accepted.status_code == 201, accepted.text


def test_waiting_login_attempts_are_counted_once(tmp_path: Path) -> None:
    """验证同一等待期五次登录只追加一行且次数为5，等待结束后正常另记一条。"""
    with job_api_case(tmp_path) as case:
        for _ in range(5):
            case.login(secret=SecretStr("wrong-password-value"))
        with session_scope(case.engine, read_only=True) as session:
            before = len(session.scalars(select(LoginLogRow)).all())
        for _ in range(5):
            assert case.login().status_code == 429
        with session_scope(case.engine, read_only=True) as session:
            rows = session.scalars(select(LoginLogRow).order_by(LoginLogRow.log_id)).all()
            assert len(rows) == before + 1
            assert rows[-1].attempt_count == 5
        case.clock.value += timedelta(seconds=61)
        assert case.login().status_code == 200
        with session_scope(case.engine, read_only=True) as session:
            after = session.scalars(select(LoginLogRow).order_by(LoginLogRow.log_id)).all()
            assert len(after) == len(rows) + 1 and after[-1].attempt_count == 1


@pytest.mark.parametrize("streaming", [False, True])
def test_request_body_limit(tmp_path: Path, streaming: bool) -> None:
    """验证超过16MiB的请求在JSON解析之前得到413和五段诊断。"""
    with job_api_case(tmp_path) as case:
        body = b"x" * (16 * 1024 * 1024 + 1)
        response = case.client.post("/api/auth/login", content=iter((body,)) if streaming else body)
        assert response.status_code == 413
        assert response.json()["diagnostics"]


def test_database_files_are_private(tmp_path: Path) -> None:
    """验证新建数据库及仍存在的WAL、SHM文件均为0600。"""
    with job_api_case(tmp_path) as case, case.engine.connect():
        for suffix in ("", "-wal", "-shm"):
            path = tmp_path / ("rdp.sqlite3" + suffix)
            if path.exists():
                assert path.stat().st_mode & 0o777 == 0o600


def test_expected_rejection_log_level(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """验证401只记INFO且无traceback，程序缺陷仍记ERROR。"""
    with job_api_case(tmp_path) as case:
        with caplog.at_level(logging.INFO, logger="rdp.api.errors"):
            assert case.client.get("/api/jobs").status_code == 401
        records = [record for record in caplog.records if record.name == "rdp.api.errors"]
        assert records and all(record.levelno < logging.ERROR for record in records)
        assert all("Traceback" not in record.getMessage() for record in records)
        member = add_actor(case)

        def defect() -> None:
            raise RuntimeError("关键验收的5xx")

        case.app.add_api_route("/api/cleanup-defect", defect, methods=["GET"])
        case.app.router.routes.insert(0, case.app.router.routes.pop())
        caplog.clear()
        response = case.client.get(
            "/api/cleanup-defect",
            headers={"Cookie": "rdp_session=" + member.token.get_secret_value()},
        )
        assert response.status_code == 500
        errors = [record for record in caplog.records if record.name == "rdp.api.errors"]
        assert len(errors) == 1 and errors[0].levelno == logging.ERROR


def test_member_job_diagnostics_and_log_are_redacted(tmp_path: Path) -> None:
    """验证成员的详情、列表和日志去掉路径、argv和stderr，管理员仍看原始五段诊断。"""
    from accounts_support import NOW
    from pydantic import TypeAdapter

    from rdp.infra.diagnostics import (
        Diagnostic,
        DiagnosticCategory,
        DiagnosticGroup,
        DiagnosticLevel,
        DiagnosticObject,
        ExternalError,
        aggregate_diagnostics,
        render_diagnostic,
    )
    from rdp.jobs.models import JobRow
    from rdp.jobs.records import StateChange, transition_job
    from rdp.jobs.types import JobState

    diagnostic = Diagnostic(
        level=DiagnosticLevel.ERROR,
        category=DiagnosticCategory.EXTERNAL,
        stage="外部工具",
        source="/private/tool",
        objects=(
            DiagnosticObject(key="path", value="/private/storage/source.json"),
            DiagnosticObject(key="command", value="('/private/bin/tool', '--private-flag')"),
            DiagnosticObject(key="stderr_tail", value="private-stderr-content"),
            DiagnosticObject(key="exit_code", value="2"),
        ),
        rule="工具必须成功退出",
        actual="读取/private/storage/source.json失败",
        expected="退出码0",
        consequence="作业失败",
        next_step="联系管理员检查日志",
    )
    with job_api_case(tmp_path) as case:
        case.login()
        member = add_actor(case)
        job = case.client.post("/api/jobs/example", json={"steps": 1, "interval_ms": 0}).json()
        identifier = int(job["job_id"])
        log_path = "logs/示例：数数/private.log"
        with session_scope(case.engine) as session:
            transition_job(
                session,
                identifier,
                StateChange(JobState.QUEUED, JobState.RUNNING, NOW, log_path=log_path),
            )
            row = session.get(JobRow, identifier)
            assert row is not None
            row.diagnostics = TypeAdapter(tuple[DiagnosticGroup, ...]).dump_python(
                aggregate_diagnostics((diagnostic,)), mode="json"
            )
        log = tmp_path / log_path
        log.parent.mkdir(exist_ok=True)
        log.write_text(render_diagnostic(diagnostic) + "\nstderr 工具│private-stderr-content\n")
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}

        def failed_query() -> None:
            raise ExternalError((diagnostic,))

        case.app.add_api_route("/api/jobs/diagnostic-probe", failed_query, methods=["GET"])
        case.app.router.routes.insert(0, case.app.router.routes.pop())
        for path in (
            f"/api/jobs/{identifier}",
            "/api/jobs",
            f"/api/jobs/{identifier}/log",
            "/api/jobs/diagnostic-probe",
        ):
            response = case.client.get(path, headers=headers)
            assert response.status_code == (502 if path.endswith("diagnostic-probe") else 200), (
                response.text
            )
            assert "/private/" not in response.text
            assert "--private-flag" not in response.text
            assert "private-stderr-content" not in response.text
            assert "exit_code" in response.text
        admin = case.client.get(f"/api/jobs/{identifier}")
        assert "/private/" in admin.text and "--private-flag" in admin.text
        assert "private-stderr-content" in admin.text


def test_concurrent_logins_wait_without_public_pool_tokens(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证超过Argon2名额的真实登录异步排队，计算和排队都不借用公共线程池token。"""
    release, lock = Event(), Lock()
    entered = 0
    original = PasswordCodec.verify

    def verify(codec: PasswordCodec, encoded: str | None, password: SecretStr) -> PasswordCheck:
        nonlocal entered
        with lock:
            entered += 1
        if not release.wait(10):
            raise TimeoutError("测试未释放哈希计算")
        return original(codec, encoded, password)

    async def exercise(case: ApiCase) -> None:
        limiter = anyio.to_thread.current_default_thread_limiter()
        slots = anyio.CapacityLimiter(ARGON2_MAX_CONCURRENCY)
        monkeypatch.setattr(accounts, "_password_slots", slots)
        monkeypatch.setattr(
            accounts, "_password_threads", anyio.CapacityLimiter(ARGON2_MAX_CONCURRENCY)
        )
        # 此测试验证名额而非排队超时；给真实线程调度留有界余量，生产一秒预算保持不变。
        monkeypatch.setattr(accounts, "ARGON2_QUEUE_TIMEOUT_S", 10.0)
        responses: list[httpx.Response] = []
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=case.app),
            base_url="http://testserver",
            headers={"Origin": "http://testserver"},
        ) as client:

            async def login() -> None:
                responses.append(
                    await client.post(
                        "/api/auth/login",
                        json={"login_name": "admin", "password": EXAMPLE_SECRET.get_secret_value()},
                    )
                )

            async with anyio.create_task_group() as group:
                for _ in range(ARGON2_MAX_CONCURRENCY + 1):
                    group.start_soon(login)
                try:
                    with anyio.fail_after(5):
                        while (
                            slots.statistics().tasks_waiting != 1
                            or entered < ARGON2_MAX_CONCURRENCY
                        ):
                            await anyio.sleep(0.005)
                    assert entered == ARGON2_MAX_CONCURRENCY
                    assert limiter.borrowed_tokens == 0
                finally:
                    # 先释放替身运算再退出任务组，失败和取消也不会等满运算预算。
                    release.set()
        assert len(responses) == ARGON2_MAX_CONCURRENCY + 1
        # 测试只观察排队和资源；密码校验仍由真实编码器完成。
        assert all(response.status_code == 200 for response in responses), [
            response.text for response in responses
        ]
        assert slots.borrowed_tokens == 0

    with job_api_case(tmp_path) as case:
        monkeypatch.setattr(PasswordCodec, "verify", verify)
        anyio.run(exercise, case)
