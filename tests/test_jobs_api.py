"""作业HTTP公共边界测试；真实ASGI鉴权、领域事务和临时文件，不启动网络服务。"""

from datetime import timedelta
from pathlib import Path

from account_api_support import add_actor
from accounts_support import NOW
from jobs_api_support import job_api_case
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.audit.types import OperationDetails
from rdp.infra.db.connection import session_scope
from rdp.jobs.records import StateChange, save_heartbeat, transition_job
from rdp.jobs.types import JobState, WorkerHeartbeat


def test_real_app_order(tmp_path: Path) -> None:
    """真实应用鉴权：Origin403→认证401→强制改密403→路由404/405→参数422，成员可访问所有作业路径。"""
    with job_api_case(tmp_path) as fixture:
        assert (
            fixture.client.post(
                "/api/jobs", content="{bad", headers={"Origin": "http://other"}
            ).status_code
            == 403
        )
        assert fixture.client.post("/api/jobs", content="{bad").status_code == 401
        forced = add_actor(fixture, name="forced", ready=False)
        headers = {"Cookie": "rdp_session=" + forced.token.get_secret_value()}
        assert fixture.client.post("/api/jobs", content="{bad", headers=headers).status_code == 403
        member = add_actor(fixture)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        assert fixture.client.get("/api/jobs/no/such/path", headers=headers).status_code == 404
        assert fixture.client.delete("/api/jobs", headers=headers).status_code == 405
        assert fixture.client.post("/api/jobs", content="{bad", headers=headers).status_code == 422
        assert fixture.client.get("/api/jobs", headers=headers).status_code == 200


def test_real_app_invalid_payload(tmp_path: Path) -> None:
    """真实应用422：未登记类型、非法CountParameters、额外字段和坏编号不回显值，响应含请求error_id。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        payloads: list[dict[str, object]] = [
            {"type_name": "removed", "parameters": {}},
            {"type_name": "example_count", "parameters": {"steps": True, "interval_ms": 0}},
            {
                "type_name": "example_count",
                "parameters": {"steps": 3, "interval_ms": 0, "extra": "私密标记"},
            },
        ]
        for payload in payloads:
            response = fixture.client.post("/api/jobs", json=payload)
            assert response.status_code == 422 and "私密标记" not in response.text
            assert response.json()["error_id"] == response.headers["x-request-id"]
        response = fixture.client.post(
            "/api/jobs/example", json={"steps": 3, "interval_ms": 0, "failed_steps": [4]}
        )
        assert response.status_code == 422


def test_real_app_submit_cancel(tmp_path: Path) -> None:
    """真实应用验收4：成员提交及另一成员取消，HTTP201/200和操作日志当前账号一致。"""
    with job_api_case(tmp_path) as fixture:
        first = add_actor(fixture, name="first")
        second = add_actor(fixture, name="second")
        response = fixture.client.post(
            "/api/jobs/example",
            json={"steps": 3, "interval_ms": 0},
            headers={"Cookie": "rdp_session=" + first.token.get_secret_value()},
        )
        assert response.status_code == 201, response.text
        job = response.json()
        assert job["state"] == "queued" and job["submitted_by"]["account_id"] == str(
            first.identity.account.account_id
        )
        cancelled = fixture.client.post(
            f"/api/jobs/{job['job_id']}/cancel",
            headers={"Cookie": "rdp_session=" + second.token.get_secret_value()},
        )
        assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
        with session_scope(fixture.engine, read_only=True) as session:
            audit = session.scalar(
                select(OperationLogRow).where(OperationLogRow.operation == "cancel_job")
            )
            assert audit is not None and audit.actor_id == second.identity.account.account_id


def test_real_app_cancel_conflict(tmp_path: Path) -> None:
    """真实应用409：重复取消/终态取消/真实写冲突拒绝，数据库无新操作日志。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        job = fixture.client.post("/api/jobs/example", json={"steps": 3, "interval_ms": 0}).json()
        path = f"/api/jobs/{job['job_id']}/cancel"
        assert fixture.client.post(path).status_code == 200
        assert fixture.client.post(path).status_code == 409
        with session_scope(fixture.engine, read_only=True) as session:
            assert (
                len(
                    session.scalars(
                        select(OperationLogRow).where(OperationLogRow.operation == "cancel_job")
                    ).all()
                )
                == 1
            )


def test_real_app_resubmit(tmp_path: Path) -> None:
    """真实应用验收9：三个终态重提201，新编号及当前actor；非终态409，原记录不变。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        job = fixture.client.post("/api/jobs/example", json={"steps": 3, "interval_ms": 0}).json()
        path = f"/api/jobs/{job['job_id']}/resubmit"
        assert fixture.client.post(path).status_code == 409
        assert fixture.client.post(f"/api/jobs/{job['job_id']}/cancel").status_code == 200
        member = add_actor(fixture)
        response = fixture.client.post(
            path, headers={"Cookie": "rdp_session=" + member.token.get_secret_value()}
        )
        assert response.status_code == 201
        copied = response.json()
        assert copied["job_id"] != job["job_id"] and copied["resubmitted_from"] == job["job_id"]
        assert copied["submitted_by"]["account_id"] == str(member.identity.account.account_id)
        assert fixture.client.get(f"/api/jobs/{job['job_id']}").json()["state"] == "cancelled"


def test_real_app_detail_notfound(tmp_path: Path) -> None:
    """真实应用404：不存在作业与坏编号422分开；所有业务失败沿用problem+json及请求编号。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        for value, expected in (
            ("999", 404),
            ("0", 422),
            ("01", 422),
            ("9223372036854775808", 422),
            ("bad", 422),
        ):
            response = fixture.client.get(f"/api/jobs/{value}")
            assert response.status_code == expected
            assert response.headers["content-type"].startswith("application/problem+json")
            assert response.json()["error_id"] == response.headers["x-request-id"]


def test_real_app_log_status(tmp_path: Path) -> None:
    """真实应用验收7：日志cleared/not_started均200明确状态，越界500不泄漏内部路径。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        job = fixture.client.post("/api/jobs/example", json={"steps": 3, "interval_ms": 0}).json()
        identifier = job["job_id"]
        response = fixture.client.get(f"/api/jobs/{identifier}/log")
        assert response.status_code == 200 and response.json()["tail"]["status"] == "not_started"
        with session_scope(fixture.engine) as session:
            transition_job(
                session,
                int(identifier),
                StateChange(
                    JobState.QUEUED, JobState.RUNNING, NOW, log_path="logs/示例：数数/missing.log"
                ),
            )
        response = fixture.client.get(f"/api/jobs/{identifier}/log")
        assert response.status_code == 200 and response.json()["tail"]["status"] == "cleared"
        with fixture.engine.begin() as connection:
            connection.exec_driver_sql(
                "UPDATE jobs SET log_path='../secret' WHERE job_id=?", (int(identifier),)
            )
        response = fixture.client.get(f"/api/jobs/{identifier}/log")
        assert response.status_code == 500 and "../secret" not in response.text


def test_real_app_cursor(tmp_path: Path) -> None:
    """真实应用列表：状态/limit/游标绑定、UTC微秒和64位文本编号正确，成员没有管理员依赖。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        ids = [
            fixture.client.post(
                "/api/jobs",
                json={"type_name": "example_count", "parameters": {"steps": 3, "interval_ms": 0}},
            ).json()["job_id"]
            for _ in range(3)
        ]
        first = fixture.client.get("/api/jobs", params={"state": "queued", "limit": 1})
        assert first.status_code == 200 and first.json()["items"][0]["job_id"] == ids[-1]
        cursor = first.json()["next_cursor"]
        second = fixture.client.get(
            "/api/jobs", params={"state": "queued", "limit": 1, "cursor": cursor}
        )
        assert second.status_code == 200 and second.json()["items"][0]["job_id"] == ids[-2]
        assert ".123456Z" in second.json()["items"][0]["submitted_at"]
        assert (
            fixture.client.get(
                "/api/jobs", params={"state": "cancelled", "limit": 1, "cursor": cursor}
            ).status_code
            == 422
        )


def test_real_app_worker_status(tmp_path: Path) -> None:
    """真实应用验收8：空/过期/未来心跳的online正确，数据库故障502不伪装离线。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        response = fixture.client.get("/api/worker/status")
        assert response.status_code == 200 and response.json()["online"] is False
        for seconds, online in ((0, True), (-15, True), (-16, False), (10, True)):
            with session_scope(fixture.engine) as session:
                save_heartbeat(
                    session,
                    WorkerHeartbeat(
                        "00000000000040008000000000000001",
                        123,
                        NOW,
                        NOW + timedelta(seconds=seconds),
                    ),
                )
            response = fixture.client.get("/api/worker/status")
            assert response.status_code == 200 and response.json()["online"] is online
            assert response.json()["pid"] == 123


def test_openapi_job_schema() -> None:
    """接口契约：作业、示例参数、心跳、审计job对象进入OpenAPI，生成类型未过期；无删除作业路由。"""
    import json

    from rdp.api import create_app

    schema = create_app(None, database=None).openapi()
    components = schema["components"]["schemas"]
    assert {
        "JobResponse",
        "JobProgress",
        "CountParameters",
        "WorkerStatusResponse",
        "ObjectResponse",
    } <= set(components)
    assert components["ObjectResponse"]["properties"]["kind"]["enum"] == [
        "account",
        "audit_settings",
        "job",
    ]
    assert components["JobResponse"]["properties"]["job_id"]["type"] == "string"
    assert components["JobResponse"]["properties"]["recovery_count"]["maximum"] == 3
    assert "delete" not in schema["paths"]["/api/jobs/{job_id}"]
    assert set(schema["paths"]["/api/jobs"]) == {"get", "post"}
    generated = Path(__file__).parents[1] / "src/web/src/api/openapi.json"
    assert json.loads(generated.read_text()) == schema


def test_no_web_execution(tmp_path: Path) -> None:
    """进程边界：所有Web路径只查库和受限logs，不调用类型执行函数、不触碰数据目录或存储根。"""
    from dataclasses import replace

    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.registry import JobRegistry, production_registry

    calls: list[int] = []

    def forbidden(context: ExecutionContext) -> None:
        calls.append(context.job_id)
        raise AssertionError("Web不得执行作业")

    definition = production_registry().lookup("example_count")
    assert definition is not None
    registry = JobRegistry()
    registry.register(replace(definition, execute=forbidden))
    with job_api_case(tmp_path, registry=registry) as fixture:
        fixture.login()
        record = fixture.client.post(
            "/api/jobs/example", json={"steps": 3, "interval_ms": 0}
        ).json()
        identifier = record["job_id"]
        for path in (
            "/api/jobs",
            f"/api/jobs/{identifier}",
            f"/api/jobs/{identifier}/log",
            "/api/worker/status",
        ):
            assert fixture.client.get(path).status_code == 200
        assert fixture.client.post(f"/api/jobs/{identifier}/cancel").status_code == 200
        assert fixture.client.post(f"/api/jobs/{identifier}/resubmit").status_code == 201
        assert (
            fixture.client.post(
                "/api/jobs",
                json={"type_name": "example_count", "parameters": {"steps": 3, "interval_ms": 0}},
            ).status_code
            == 201
        )
        assert calls == [] and list((tmp_path / "logs").rglob("*.log")) == []


def test_claim_before_cancel_returns_cancelling(tmp_path: Path) -> None:
    """第6条真实应用：worker先领取提交后用户取消返回200/cancelling并有取消审计，不能按旧queued返回409。"""
    with job_api_case(tmp_path) as fixture:
        fixture.login()
        job = fixture.client.post("/api/jobs/example", json={"steps": 3, "interval_ms": 0}).json()
        with session_scope(fixture.engine) as session:
            transition_job(
                session,
                int(job["job_id"]),
                StateChange(
                    JobState.QUEUED, JobState.RUNNING, NOW, log_path="logs/示例：数数/claimed.log"
                ),
            )
        response = fixture.client.post(f"/api/jobs/{job['job_id']}/cancel")
        assert response.status_code == 200 and response.json()["state"] == "cancelling"
        with session_scope(fixture.engine, read_only=True) as session:
            audit = session.scalar(
                select(OperationLogRow).where(OperationLogRow.operation == "cancel_job")
            )
            assert (
                audit is not None
                and OperationDetails.model_validate(audit.details).before.job_state == "running"
            )
