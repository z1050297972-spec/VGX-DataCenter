"""M5-08 验收：经真实 HTTP 和 worker 检查就绪，远程脚本只在本机假程序上运行。"""

import json
import socket
from pathlib import Path

from jobs_api_support import job_api_case
from robot_connection_support import readiness_ssh, run, submit


def test_disconnected_eth1_warns_without_failing_running_stack(tmp_path: Path) -> None:
    """验收 1：发现服务器和厂商进程在跑但 eth1 缺地址，带警告成功且解释重启风险。"""
    program = readiness_ssh(tmp_path, missing="address")
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        run(api, job_id, program)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "succeeded_with_warnings", job
        assert job["progress"]["stage_name"] == "网络：通过；登录：通过；就绪：有警告"
        assert job["progress"]["warning_count"] == 1
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert diagnostic["level"] == "warning"
        assert diagnostic["stage"] == "第 3 层 就绪"
        assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
        assert "不满足" in diagnostic["actual"]
        assert "继续" in diagnostic["consequence"]
        assert diagnostic["next_step"] == (
            "eth1（主臂网线）断开：已在跑的厂商程序照常工作，但这时重启厂商栈会互相发现不了、"
            "录出空数据。重启前先接通主臂（0008、0014）"
        )


def test_missing_hdas_fails_at_readiness_with_profile_reason(tmp_path: Path) -> None:
    """验收 2：HDAS 缺失只在第 3 层失败，下一步原样使用说明档的原因。"""
    program = readiness_ssh(tmp_path, missing="HDAS")
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        run(api, job_id, program)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "failed", job
        assert job["progress"]["stage_name"] == "网络：通过；登录：通过；就绪：失败"
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert diagnostic["stage"] == "第 3 层 就绪"
        assert diagnostic["level"] == "error"
        assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
        assert "process_running" in diagnostic["actual"]
        assert "失败" in diagnostic["consequence"]
        assert diagnostic["next_step"] == (
            "手臂驱动 HDAS 没在跑：厂商软件栈没启动或已退出。"
            "先确认主臂网线接通，再执行 boot.sh（0014）"
        )


def test_profile_value_is_literal_in_stdin_not_remote_command(tmp_path: Path) -> None:
    """验收 4：真实 bash 接收含注入文本的脚本，值仅按固定文本匹配，远程命令只有 bash -s。"""
    marker = tmp_path / "injected"
    value = f"HDAS/HDAS'; touch {marker} # $(touch {marker}) [literal]"
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    source = (Path(__file__).parents[1] / "profiles/r1lite.toml").read_text()
    (profiles / "r1lite.toml").write_text(source.replace('"HDAS/HDAS"', json.dumps(value)))
    program = readiness_ssh(tmp_path, missing="", process_text=value)
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        _, job_id = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        run(api, job_id, program, profiles_dir=profiles)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "succeeded", job
        assert job["progress"]["stage_name"] == "网络：通过；登录：通过；就绪：通过"
        assert job["progress"]["done"] == job["progress"]["total"] == 3
        assert job["diagnostics"] == []
        arguments = json.loads((tmp_path / "received-argv").read_text())
        assert arguments[arguments.index("--") + 2 :] == ["bash", "-s"]
        assert value not in str(arguments)
        assert "touch" in (tmp_path / "received-script").read_text()
        assert not marker.exists()
