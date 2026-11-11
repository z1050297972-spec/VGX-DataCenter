"""M5-08 验收：经真实 HTTP 和 worker 检查就绪，远程脚本只在本机假程序上运行。"""

import json
import socket
from pathlib import Path

import pytest
from jobs_api_support import job_api_case
from robot_connection_support import readiness_ssh, run, submit


@pytest.mark.parametrize("failure", ["", "missing", "exit", "timeout"])
def test_hdas_node_visibility_controls_readiness_without_leaving_files(
    tmp_path: Path, failure: str
) -> None:
    """M5-11 验收 1-3：完整节点名才通过，查询失败拒绝就绪，成功与失败均清理 ROS 临时目录。"""
    program = readiness_ssh(tmp_path, missing="", ros_failure=failure)
    profile_path = tmp_path / "profiles/r1lite.toml"
    home = tmp_path / "robot-home"
    before = list(home.rglob("*"))
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        run(api, job_id, program, profiles_dir=profile_path.parent)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == ("failed" if failure else "succeeded"), job
        if failure:
            diagnostic = job["diagnostics"][0]["samples"][0]
            assert diagnostic["stage"] == "第 3 层 就绪"
            assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
            assert diagnostic["actual"] == "ros_node_visible 条件不满足"
            assert "失败" in diagnostic["consequence"]
            assert diagnostic["next_step"] == (
                "厂商节点没在本机发现服务器报到：多半是厂商栈在 eth1（主臂网线）断开时启动的，"
                "节点之间互相发现不了，这时采集会录出空数据。先接通主臂网线，确认 eth1 有 10.42.0.238；"
                "节点一般会在几十秒内自行报到，之后再检查一次；仍然看不到，"
                "再执行 robot_startup.sh kill 和 boot.sh（0014）"
            )
        else:
            assert job["diagnostics"] == []
    record = json.loads((tmp_path / "ros-observation").read_text())
    temporary = Path(record["FASTRTPS_DEFAULT_PROFILES_FILE"]).parent
    assert Path(record["ROS_HOME"]).is_relative_to(temporary)
    assert Path(record["ROS_LOG_DIR"]).is_relative_to(temporary)
    assert record["xml"] == (
        "<profiles><address>127.0.0.1</address><address>127.0.0.1</address></profiles>"
    )
    assert not temporary.exists()
    assert list(home.rglob("*")) == before
    assert (tmp_path / "readiness-vendor/discovery.xml").read_text() == (
        "<profiles><address>10.0.0.1</address><address>10.0.0.2</address></profiles>"
    )


def test_disconnected_eth1_warns_without_failing_running_stack(tmp_path: Path) -> None:
    """验收 1：发现服务器和厂商进程在跑但 eth1 缺地址，带警告成功且解释重启风险。"""
    program = readiness_ssh(tmp_path, missing="address")
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        run(api, job_id, program, profiles_dir=tmp_path / "profiles")
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
            "eth1（主臂网线）断开：主臂没接或没上电。这时启动或重启的厂商节点报到不了，"
            "采集会录出空数据；接通后节点一般会自行报到（0008、0014）"
        )


def test_missing_hdas_fails_at_readiness_with_profile_reason(tmp_path: Path) -> None:
    """验收 2：HDAS 缺失只在第 3 层失败，下一步原样使用说明档的原因。"""
    program = readiness_ssh(tmp_path, missing="HDAS")
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        run(api, job_id, program, profiles_dir=tmp_path / "profiles")
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
    program = readiness_ssh(tmp_path, missing="", process_text=value)
    profiles = tmp_path / "profiles"
    path = profiles / "r1lite.toml"
    path.write_text(path.read_text().replace('"HDAS/HDAS"', json.dumps(value)))
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
