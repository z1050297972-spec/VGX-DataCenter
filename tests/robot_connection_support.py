"""SSH 验收装配：真实 HTTP/作业执行器，所有文件在 tmp，SSH 仅为假程序。"""

import time
from pathlib import Path
from threading import Event, Lock

from account_api_support import ApiCase
from jobs_scheduling_support import claim_fixture, resources_fixture

from rdp.infra.db.connection import session_scope
from rdp.jobs.execution import ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import production_registry
from rdp.jobs.robot_connection.job import ConnectionDependencies
from rdp.jobs.types import ExecutionMode, JobClock


def fake_ssh(root: Path, body: str) -> Path:
    """创建不会联网的可执行假 SSH；行为由验收样本决定。"""
    program = root / "fake-ssh"
    program.write_text("#!/bin/sh\n" + body)
    program.chmod(0o700)
    return program


def submit(api: ApiCase, port: int) -> tuple[int, str]:
    """只登记回环地址，经公开接口提交连接检查。"""
    response = api.client.post(
        "/api/robots",
        json={
            "name": "回环机器人",
            "robot_model": "测试型号",
            "address": "127.0.0.1",
            "ssh_user": "tester",
            "ssh_port": port,
        },
    )
    assert response.status_code == 201, response.text
    robot_id = response.json()["robot_id"]
    job = api.client.post(
        "/api/jobs",
        json={"type_name": "robot_connection_check", "parameters": {"robot_id": robot_id}},
    )
    assert job.status_code == 201, job.text
    return robot_id, job.json()["job_id"]


def run(api: ApiCase, job_id: str, program: Path) -> None:
    """真实领取并执行作业，注入的仅是系统 SSH 可执行文件边界。"""
    paths = api.app.state.job_paths
    registry = production_registry(
        connection_dependencies=ConnectionDependencies(api.engine, paths, ssh=program)
    )
    with session_scope(api.engine) as session:
        record = claim_job(session, int(job_id), now=api.clock(), paths=paths, gpu_index=None)
    dependencies = ExecutorDependencies(
        api.engine,
        registry,
        paths,
        JobClock(api.clock, time.monotonic),
        resources=resources_fixture(registry),
        storage=None,
    )
    signals = ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
    assert (
        execute_job(
            ExecutionWork(
                record, ExecutionMode.FRESH, None, claim=claim_fixture(record, dependencies)
            ),
            dependencies,
            signals,
        )
        is not None
    )
