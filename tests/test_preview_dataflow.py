"""M5-12 B 路验收：纯判定和真实开启作业；机器人仅使用本机假程序。"""

import json
import os
import socket
from pathlib import Path

import pytest
from jobs_api_support import job_api_case
from preview_start_stop_support import execute_preview, install_wheel, reap_relay, submit_preview
from robot_connection_support import submit
from test_preview_start_stop import prepare

from rdp.collection.preview_config import build_relay_config
from rdp.collection.preview_dataflow import evaluate_dataflow
from rdp.collection.profile import load_robot_profiles


def test_dataflow_classifies_camera_observation_and_idle_target() -> None:
    """相机无数据失败、观测 40% 警告、目标静默提示，其余原始频率达到阈值通过。"""
    profile = next(
        p for p in load_robot_profiles(Path("profiles").resolve()) if p.profile == "r1lite"
    )
    routes = build_relay_config(profile, "127.0.0.1")["routes"]
    assert isinstance(routes, list)
    counts = {r["channel"]: 1000 for r in routes if isinstance(r, dict)}
    counts["/viz/camera/head_left"] = 0
    counts["/viz/joint/left_arm/obs"] = 400
    counts["/viz/joint/left_arm/target"] = 0
    results = evaluate_dataflow(
        profile, routes, "RDP_VIZ_PROBE " + json.dumps({"window_s": 5.0, "counts": counts})
    )
    by_channel = {result.channel: result for result in results}
    assert by_channel["/viz/camera/head_left"].status == "失败"
    assert by_channel["/viz/joint/left_arm/obs"].status == "警告"
    assert by_channel["/viz/joint/left_arm/obs"].actual_hz == 80.0
    assert by_channel["/viz/joint/left_arm/target"].status == "提示"
    assert sum(result.status == "通过" for result in results) == 12


@pytest.mark.parametrize(
    ("probe_state", "outcome"),
    [
        ("passing", "succeeded"),
        ("silent_observation", "failed"),
        ("bad_json", "succeeded_with_warnings"),
    ],
)
def test_start_reports_dataflow_and_preserves_relay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe_state: str, outcome: str
) -> None:
    """全部通过成功、观测无数据失败、坏 JSON 警告成功；三种结果都保留预览进程。"""
    setup = prepare(tmp_path, monkeypatch)
    home = tmp_path / "robot-home"
    if probe_state == "bad_json":
        (home / "probe-output").write_text("RDP_VIZ_PROBE {broken")
    elif probe_state == "silent_observation":
        profile = load_robot_profiles(setup[1])[0]
        routes = build_relay_config(profile, "127.0.0.1")["routes"]
        assert isinstance(routes, list)
        counts = {r["channel"]: 1000 for r in routes if isinstance(r, dict)}
        counts["/viz/joint/left_arm/obs"] = 0
        (home / "probe-output").write_text(
            "RDP_VIZ_PROBE " + json.dumps({"window_s": 5.0, "counts": counts})
        )
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api, reap_relay(home):
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, _ = submit(api, endpoint.getsockname()[1], model="Galaxea R1 Lite")
        install_wheel(api)
        job_id = submit_preview(api, robot_id, "start")
        execute_preview(api, job_id, setup)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == outcome, job
        pid = int((home / "rdp_viz/run/relay.pid").read_text())
        os.kill(pid, 0)
        if probe_state == "passing":
            assert "数据流：15 路通过" in job["progress"]["stage_name"]
        else:
            diagnostic = job["diagnostics"][0]["samples"][0]
            if probe_state == "silent_observation":
                assert diagnostic["level"] == "error"
                assert diagnostic["actual"] == "/viz/joint/left_arm/obs 5 秒内 0 条"
                assert "已开启并保持运行" in diagnostic["consequence"]
            else:
                assert diagnostic["level"] == "warning"
                assert diagnostic["actual"] == "数据流检查没做成"
                assert diagnostic["next_step"] == "看机器人上 ~/rdp_viz/log/probe.log"
        assert job["progress"]["done"] == job["progress"]["total"] == 6
