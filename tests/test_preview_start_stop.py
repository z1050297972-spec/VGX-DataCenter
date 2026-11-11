"""M5-09 作业验收：HTTP 到真实执行器和 bash，系统边界使用假机器人。"""

import os
import socket
import subprocess
from pathlib import Path

import pytest
from jobs_api_support import job_api_case
from jobs_process_resources import reap_known
from preview_start_stop_support import (
    execute_preview,
    install_wheel,
    prepare,
    reap_relay,
    submit_preview,
)
from robot_connection_support import submit


def test_first_start_installs_only_in_rdp_viz(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 1/8：首启真实执行脚本，校验离线安装、ROS 环境及路径引号，仅写 rdp_viz。"""
    setup = prepare(tmp_path, monkeypatch)
    home = tmp_path / "robot-home"
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api, reap_relay(home):
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, _ = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        install_wheel(api)
        job_id = submit_preview(api, robot_id, "start")
        execute_preview(api, job_id, setup)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "succeeded", job
        assert "ws://127.0.0.1:8765" in job["progress"]["stage_name"]
        assert {p.name for p in home.iterdir()} == {"rdp_viz"}
        assert (home / "rdp_viz/self-tested").exists()
        assert (tmp_path / "vendor/discovery.xml").read_text() == (
            "<profiles><address>10.0.0.1</address><address>10.0.0.2</address></profiles>"
        )
        assert (home / "rdp_viz/fastdds_local.xml").read_text() == (
            "<profiles><address>127.0.0.1</address><address>127.0.0.1</address></profiles>"
        )
        assert (
            home / "rdp_viz/wheels" / "foxglove_sdk-0.30.3-cp310-abi3-manylinux_2_28_aarch64.whl"
        ).read_bytes() == b"test-wheel"


def test_repeated_start_keeps_process_and_uploaded_wheel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 2：同包再次开启复用进程和 wheel，不重复上传；eth1 警告保留。"""
    setup = prepare(tmp_path, monkeypatch, missing="address")
    home = tmp_path / "robot-home"
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api, reap_relay(home):
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, _ = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        install_wheel(api)
        first = submit_preview(api, robot_id, "start")
        execute_preview(api, first, setup)
        assert (
            api.client.get(f"/api/jobs/{first}").json()["summary"]["outcome"]
            == "succeeded_with_warnings"
        )
        pidfile = home / "rdp_viz/run/relay.pid"
        pid = pidfile.read_text()
        wheel = next((home / "rdp_viz/wheels").glob("*.whl"))
        stat = wheel.stat()
        second = submit_preview(api, robot_id, "start")
        execute_preview(api, second, setup)
        job = api.client.get(f"/api/jobs/{second}").json()
        assert job["summary"]["outcome"] == "succeeded_with_warnings", job
        assert "已在运行" in job["progress"]["stage_name"]
        assert pidfile.read_text() == pid
        assert (wheel.stat().st_ino, wheel.stat().st_mtime_ns) == (stat.st_ino, stat.st_mtime_ns)


@pytest.mark.parametrize("failure", ["port", "readiness", "wheel"])
def test_start_refuses_unavailable_prerequisite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """验收 3/4/6：占用端口不启动，就绪错误和缺 wheel 不上传，诊断给出下一步。"""
    setup = prepare(tmp_path, monkeypatch, missing="HDAS" if failure == "readiness" else "")
    home = tmp_path / "robot-home"
    if failure == "port":
        (home / "occupied").touch()
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api, reap_relay(home):
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, _ = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        if failure != "wheel":
            install_wheel(api)
        job_id = submit_preview(api, robot_id, "start")
        execute_preview(api, job_id, setup)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "failed", job
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert not (home / "rdp_viz/run/relay.pid").exists()
        if failure == "port":
            assert (
                diagnostic["next_step"]
                == "机器人上 8765 端口被别的程序占用；平台不会去停它，先查是谁在用"
            )
        else:
            assert not (home / "rdp_viz").exists()
            if failure == "readiness":
                assert diagnostic["stage"] == "第 3 层 就绪"
            else:
                assert (
                    "rdp install-viz-relay-wheel /本地路径/foxglove_sdk-" in diagnostic["next_step"]
                )


@pytest.mark.parametrize("state", ["running", "unrelated", "absent"])
def test_stop_only_terminates_owned_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    """验收 5：停止自己的进程，陈旧记录不杀无关进程，无记录时幂等成功；停止不查就绪。"""
    setup = prepare(tmp_path, monkeypatch, missing="" if state == "running" else "HDAS")
    home = tmp_path / "robot-home"
    unrelated = subprocess.Popen(["/bin/sleep", "60"]) if state == "unrelated" else None
    pid: int | None = None
    try:
        with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api, reap_relay(home):
            endpoint.bind(("127.0.0.1", 0))
            endpoint.listen()
            api.login()
            robot_id, _ = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
            pidfile = home / "rdp_viz/run/relay.pid"
            if state == "running":
                install_wheel(api)
                start = submit_preview(api, robot_id, "start")
                execute_preview(api, start, setup)
                assert (
                    api.client.get(f"/api/jobs/{start}").json()["summary"]["outcome"] == "succeeded"
                )
                pid = int(pidfile.read_text())
            elif unrelated:
                pidfile.parent.mkdir(parents=True)
                pidfile.write_text(str(unrelated.pid))
            job_id = submit_preview(api, robot_id, "stop")
            execute_preview(api, job_id, setup)
            job = api.client.get(f"/api/jobs/{job_id}").json()
            assert job["summary"]["outcome"] == "succeeded", job
            assert not pidfile.exists()
            if unrelated:
                assert unrelated.poll() is None
            elif pid:
                # 回收后确认不存在，不能只因 pidfile 被删就误判进程已停。

                reap_known(pid)
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
            else:
                assert "本来就没在运行" in job["progress"]["stage_name"]
    finally:
        if unrelated:
            unrelated.kill()
            unrelated.wait(timeout=2)


def test_corrupt_upload_is_rejected_on_robot_before_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验收 1：传输途中改变 wheel 字节，机器人独立核对摘要，拒绝后不创建 venv。"""
    setup = prepare(tmp_path, monkeypatch)
    ssh, _, _ = setup
    ssh.write_text(
        ssh.read_text().replace(
            "script = sys.stdin.read()",
            "script = sys.stdin.read().replace('dGVzdC13aGVlbA==', 'Y29ycnVwdA==')",
        )
    )
    home = tmp_path / "robot-home"
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api, reap_relay(home):
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, _ = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        install_wheel(api)
        job_id = submit_preview(api, robot_id, "start")
        execute_preview(api, job_id, setup)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "failed", job
        assert job["diagnostics"][0]["samples"][0]["actual"] == "机器人收到的 wheel sha256 不符"
        assert not (home / "rdp_viz/venv").exists()
        assert not list((home / "rdp_viz/wheels").iterdir())
