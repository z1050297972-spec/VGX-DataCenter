"""M5-02 验收：HTTP 可见结果经真实 worker 生成，不接触任何真实机器人。"""

import socket
from pathlib import Path

import pytest
from jobs_api_support import job_api_case
from robot_connection_support import fake_ssh, run, submit


def test_closed_port_stops_before_login(tmp_path: Path) -> None:
    """验收 1：未监听回环端口使作业失败，网络层提示核对地址且不执行 SSH。"""
    marker = tmp_path / "ssh-executed"
    program = fake_ssh(tmp_path, f"touch '{marker}'\nexit 0\n")
    # 只绑定不监听，保留端口直到断言结束，避免端口被其他测试抢走。
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1])
        run(api, job_id, program)
        response = api.client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200, response.text
        job = response.json()
        assert job["summary"]["outcome"] == "failed"
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert diagnostic["stage"] == "第 1 层 网络"
        assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
        assert "TCP" in diagnostic["actual"]
        assert "登录" in diagnostic["consequence"]
        assert "核对地址" in diagnostic["next_step"]
        assert "登录：未执行" in job["progress"]["stage_name"]
        assert not marker.exists()


def test_rejected_key_explains_manual_install(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """验收 2：拒绝公钥给出手动安装命令；SSH 原始输出中的敏感内容不进诊断和日志。"""
    output_marker = "PRIVATE-OUTPUT-MUST-NOT-BE-LOGGED"
    program = fake_ssh(
        tmp_path,
        f"echo '{output_marker}'\necho '{output_marker}' >&2\n"
        "echo 'Permission denied (publickey).' >&2\nexit 255\n",
    )
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1])
        run(api, job_id, program)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "failed"
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert diagnostic["stage"] == "第 2 层 登录"
        assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
        assert "公钥" in diagnostic["actual"] and "失败" in diagnostic["consequence"]
        assert "ssh-copy-id" in diagnostic["next_step"]
        assert "tester@127.0.0.1" in diagnostic["next_step"]
        assert f"-p {endpoint.getsockname()[1]}" in diagnostic["next_step"]
        assert job["progress"]["stage_name"] == "网络：通过；登录：失败；就绪：未执行"
        assert output_marker not in str(job)
        assert output_marker not in api.client.get(f"/api/jobs/{job_id}/log").text
        assert output_marker not in caplog.text


def test_changed_host_key_requires_manual_confirmation(tmp_path: Path) -> None:
    """验收 2：主机密钥变化不得继续或自动清记录；诊断要求确认后由管理员删对应行。"""
    program = fake_ssh(
        tmp_path, "echo 'WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!' >&2\nexit 255\n"
    )
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1])
        ssh_dir = tmp_path / "state/ssh"
        ssh_dir.mkdir()
        known_hosts = ssh_dir / "known_hosts"
        known_hosts.write_text("existing-host-key\n")
        run(api, job_id, program)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "failed"
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
        assert diagnostic["stage"] == "第 2 层 登录"
        assert "主机密钥" in diagnostic["actual"] and "失败" in diagnostic["consequence"]
        assert "确认" in diagnostic["next_step"] and "管理员删除" in diagnostic["next_step"]
        assert "known_hosts" in diagnostic["next_step"]
        assert "ssh-copy-id" not in diagnostic["next_step"]
        assert known_hosts.read_text() == "existing-host-key\n"


def test_missing_profile_warns_after_checking_current_registration(tmp_path: Path) -> None:
    """M5-08 验收 3：采用最新登记完成登录；型号没有 Profile 时跳过就绪并带警告成功。"""
    program = fake_ssh(tmp_path, "exit 1\n")
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        api.login()
        robot_id, job_id = submit(api, 1)
        current = {
            "name": "回环机器人",
            "robot_model": "测试型号",
            "address": "127.0.0.1",
            "ssh_port": endpoint.getsockname()[1],
            "ssh_user": "new-user",
        }
        changed = api.client.put(f"/api/robots/{robot_id}", json=current)
        assert changed.status_code == 200, changed.text
        # 假程序在系统边界核验安全契约；一旦改成别的远程命令或身份，返回非零。
        program.write_text(
            "#!/usr/bin/python3\nimport sys\nfrom pathlib import Path\na = sys.argv[1:]\n"
            "assert a[-2:] == ['127.0.0.1', 'true']\n"
            "assert a[a.index('-l') + 1] == 'new-user'\n"
            f"assert a[a.index('-p') + 1] == '{endpoint.getsockname()[1]}'\n"
            "assert a[a.index('-F') + 1] == '/dev/null'\n"
            "assert 'BatchMode=yes' in a and 'IdentitiesOnly=yes' in a\n"
            "assert 'StrictHostKeyChecking=accept-new' in a and 'IdentityAgent=none' in a\n"
            f"assert a[a.index('-i') + 1] == {str(tmp_path / 'state/ssh/id_ed25519')!r}\n"
            f"assert {'UserKnownHostsFile=' + str(tmp_path / 'state/ssh/known_hosts')!r} in a\n"
        )
        run(api, job_id, program)
        job = api.client.get(f"/api/jobs/{job_id}").json()
        assert job["summary"]["outcome"] == "succeeded_with_warnings", job
        assert job["progress"]["stage_name"] == "网络：通过；登录：通过；就绪：跳过"
        assert job["progress"]["warning_count"] == 1
        diagnostic = job["diagnostics"][0]["samples"][0]
        assert diagnostic["level"] == "warning"
        assert diagnostic["stage"] == "第 3 层 就绪"
        assert {"key": "robot_id", "value": str(robot_id)} in diagnostic["objects"]
        assert diagnostic["actual"] == "该型号没有 RobotProfile，未检查就绪条件"
        assert "跳过" in diagnostic["consequence"]
        assert api.client.get("/api/robots").json()["items"][0] == changed.json()


def test_public_key_is_read_only_and_private_key_stays_private(tmp_path: Path) -> None:
    """验收 4：GET 不生成密钥；worker 生成 600 私钥并复用，接口只返回单行公钥和安装命令。"""
    program = fake_ssh(tmp_path, "exit 0\n")
    with socket.socket() as endpoint, job_api_case(tmp_path / "state") as api:
        endpoint.bind(("127.0.0.1", 0))
        api.login()
        robot_id, job_id = submit(api, endpoint.getsockname()[1])
        url = f"/api/robots/ssh-public-key?robot_id={robot_id}"
        before = api.client.get(url)
        assert before.status_code == 200, before.text
        assert before.json() == {"public_key": None, "copy_command": None}
        assert not (tmp_path / "state/ssh").exists()
        run(api, job_id, program)
        private = tmp_path / "state/ssh/id_ed25519"
        secret = private.read_text()
        assert private.stat().st_mode & 0o777 == 0o600
        assert private.parent.stat().st_mode & 0o777 == 0o700
        public = api.client.get(url)
        assert public.status_code == 200, public.text
        key = public.json()["public_key"]
        assert key.startswith("ssh-ed25519 ") and "\n" not in key
        assert " rdp@" in key
        assert secret not in public.text and "PRIVATE KEY" not in public.text
        assert public.json()["copy_command"].startswith("ssh-copy-id -i ")
        again = api.client.post(f"/api/jobs/{job_id}/resubmit").json()["job_id"]
        run(api, again, program)
        assert private.read_text() == secret and api.client.get(url).json() == public.json()
        assert secret not in api.client.get(f"/api/jobs/{again}/log").text
        # 公钥文件若被误指向私钥，必须拒绝而不能沿链接读出内容。
        public_path = private.with_suffix(".pub")
        public_path.unlink()
        public_path.symlink_to(private)
        rejected = api.client.get(url)
        assert rejected.status_code == 502
        assert secret not in rejected.text and "PRIVATE KEY" not in rejected.text
