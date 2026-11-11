"""SSH 验收装配：真实 HTTP/作业执行器，所有文件在 tmp，SSH 仅为假程序。"""

import json
import shlex
import time
from pathlib import Path
from threading import Event, Lock

from account_api_support import ApiCase
from jobs_scheduling_support import claim_fixture, resources_fixture

from rdp.collection.profile import load_robot_profiles
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


def submit(api: ApiCase, port: int, *, model: str = "测试型号") -> tuple[int, str]:
    """只登记回环地址，经公开接口提交连接检查。"""
    response = api.client.post(
        "/api/robots",
        json={
            "name": "回环机器人",
            "robot_model": model,
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


def readiness_ssh(
    root: Path, *, missing: str, process_text: str = "HDAS/HDAS", ros_failure: str = ""
) -> Path:
    """假 SSH 用本机 bash 执行收到的脚本；系统探针全部替换，不访问任何网络或真实设备。"""
    probes = root / "probes"
    probes.mkdir()
    home = root / "robot-home"
    home.mkdir(exist_ok=True)
    for name, body in {
        "ip": "assert sys.argv[1:] == ['-br', 'addr']\n"
        f"print('eth1 UP {'10.42.0.23/24' if missing == 'address' else '10.42.0.238/24'}')\n",
        "ss": "assert sys.argv[1:] == ['-Huln']\nprint('UNCONN 0 0 0.0.0.0:11811 0.0.0.0:*')\n",
        "pgrep": "assert sys.argv[1:3] == ['-f', '--']\n"
        f"commands = {'signal_camera_node' if missing == 'HDAS' else process_text + ' signal_camera_node'!r}\n"
        "sys.exit(0 if re.search(sys.argv[3], commands) else 1)\n",
    }.items():
        probe = probes / name
        probe.write_text("#!/usr/bin/python3\nimport sys, re\n" + body)
        probe.chmod(0o700)
    ros2 = probes / "ros2"
    ros2.write_text(
        "#!/usr/bin/python3\nimport os, sys, json, time\nfrom pathlib import Path\n"
        "assert sys.argv[1:] == ['node', 'list', '--no-daemon', '--spin-time', '3']\n"
        "assert os.environ['LANG'] == 'C.UTF-8'\n"
        "assert os.environ['ROS_LOCALHOST_ONLY'] == '0'\n"
        "assert 'ROS_DOMAIN_ID' not in os.environ\n"
        "xml = Path(os.environ['FASTRTPS_DEFAULT_PROFILES_FILE'])\n"
        "record = {key: os.environ[key] for key in "
        "['ROS_HOME', 'ROS_LOG_DIR', 'FASTRTPS_DEFAULT_PROFILES_FILE']}\n"
        "record['xml'] = xml.read_text()\n"
        f"Path({str(root / 'ros-observation')!r}).write_text(json.dumps(record))\n"
        f"failure = {ros_failure!r}\n"
        "if failure == 'timeout': time.sleep(30)\n"
        "print('/HDAS_bridge' if failure == 'missing' else '/HDAS', flush=True)\n"
        "sys.exit(2 if failure == 'exit' else 0)\n"
    )
    ros2.chmod(0o700)
    vendor = root / "readiness-vendor"
    vendor.mkdir()
    setup = vendor / "setup'; touch injected #.bash"
    setup.write_text("export PATH=" + shlex.quote(str(probes)) + ":/usr/bin:/bin\n")
    xml = vendor / "discovery.xml"
    xml.write_text("<profiles><address>10.0.0.1</address><address>10.0.0.2</address></profiles>")
    profiles = root / "profiles"
    profiles.mkdir()
    source = (Path(__file__).parents[1] / "profiles/r1lite.toml").read_text()
    source = source.replace(
        json.dumps("/opt/ros/humble/setup.bash"), json.dumps(str(setup))
    ).replace(json.dumps("/opt/galaxea/find_server/super_client_profile.xml"), json.dumps(str(xml)))
    (profiles / "r1lite.toml").write_text(source)
    program = fake_ssh(root, "")
    program.write_text(
        "#!/usr/bin/python3\nimport sys, os, subprocess, json\nfrom pathlib import Path\n"
        "a = sys.argv[1:]\n"
        "assert a[a.index('--') + 1] == '127.0.0.1'\n"
        "if a[-1] == 'true': sys.exit(0)\n"
        "assert a[a.index('--') + 2:] == ['bash', '-s']\n"
        "assert a[a.index('-F') + 1] == '/dev/null'\n"
        "assert 'BatchMode=yes' in a and 'IdentityAgent=none' in a\n"
        "assert 'IdentitiesOnly=yes' in a and 'StrictHostKeyChecking=accept-new' in a\n"
        "script = sys.stdin.read()\n"
        f"Path({str(root / 'received-script')!r}).write_text(script)\n"
        f"Path({str(root / 'received-argv')!r}).write_text(json.dumps(a))\n"
        f"env = dict(os.environ, HOME={str(home)!r}, USER='tester', "
        f"PATH={str(probes)!r} + ':/usr/bin:/bin', ROS_DOMAIN_ID='99')\n"
        "sys.exit(subprocess.run(['/bin/bash', '-s'], input=script, text=True, "
        "env=env, cwd=env['HOME'], timeout=25, check=False).returncode)\n"
    )
    return program


def run(
    api: ApiCase,
    job_id: str,
    program: Path,
    *,
    profiles_dir: Path | None = None,
    relay_source: Path | None = None,
) -> None:
    """真实领取并执行作业，注入的仅是系统 SSH 可执行文件边界。"""
    paths = api.app.state.job_paths
    registry = production_registry(
        connection_dependencies=ConnectionDependencies(
            api.engine,
            paths,
            load_robot_profiles(
                Path(__file__).parents[1] / "profiles" if profiles_dir is None else profiles_dir
            ),
            ssh=program,
            **({"relay_source": relay_source} if relay_source is not None else {}),
        )
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
