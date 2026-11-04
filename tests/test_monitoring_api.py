"""监控接口仅通过临时 proc 快照验证，不访问真实系统或存储根。"""

from pathlib import Path

import pytest
from jobs_api_support import job_api_case
from sqlalchemy import text


def test_vpn_api_never_exposes_proxy_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Worker 环境含凭据时，接口只返回代理主机端口，不返回用户名密码。"""
    proc = tmp_path / "proc"
    worker = proc / "123"
    worker.mkdir(parents=True)
    (worker / "comm").write_text("mihomo\n")
    (worker / "environ").write_bytes(b"HTTPS_PROXY=http://alice:secret@proxy:8080\0")
    interfaces = tmp_path / "net"
    interfaces.mkdir()
    (interfaces / "tun0").mkdir()
    (interfaces / "tun0" / "tun_flags").write_text("0x1001\n")
    monkeypatch.setattr("rdp.api.monitoring.PROC_ROOT", proc)
    monkeypatch.setattr("rdp.api.monitoring.NETWORK_INTERFACES", interfaces)
    with job_api_case(tmp_path / "state") as case:
        case.login()
        now = case.clock.value.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        with case.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO worker_heartbeat (singleton_id, instance_id, pid, started_at, last_seen_at) VALUES (1, :instance, 123, :now, :now)"
                ),
                {"instance": "123e4567e89b42d3a456426614174000", "now": now},
            )
        response = case.client.get("/api/monitoring/vpn")
        assert response.status_code == 200, response.text
        assert response.json() == {
            "interfaces": "on",
            "processes": "on",
            "proxy": "on",
            "proxy_hosts": ["proxy:8080"],
        }
        assert "secret" not in response.text
        assert "alice" not in response.text


def test_mirror_api_reads_worker_result(tmp_path: Path) -> None:
    """镜像接口只读取 worker 保存的结论和检查时间。"""
    with job_api_case(tmp_path / "state") as case:
        case.login()
        with case.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO monitoring_mirror (id, status, checked_at) VALUES (1, 'ineffective', '2026-11-01T00:00:00.000000Z')"
                )
            )
        response = case.client.get("/api/monitoring/mirror")
        assert response.status_code == 200, response.text
        assert response.json() == {"status": "ineffective", "checked_at": "2026-11-01T00:00:00Z"}
        submitted = case.client.post("/api/monitoring/mirror/check")
        assert submitted.status_code == 202, submitted.text
        with case.engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT requested_seq FROM monitoring_mirror WHERE id=1")
                ).scalar_one()
                == 1
            )
            assert connection.execute(text("SELECT COUNT(*) FROM jobs")).scalar_one() == 0


def test_resource_api_samples_kernel_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """接口读取两次固定内核样本并返回网速、CPU 和内存。"""
    proc = tmp_path / "proc"
    (proc / "net").mkdir(parents=True)
    (proc / "net" / "dev").write_text("eth0: 1000 0 0 0 0 0 0 0 2000 0 0 0 0 0 0 0\n")
    (proc / "stat").write_text("cpu  100 0 50 850 0 0 0 0\n")
    (proc / "meminfo").write_text(
        "MemTotal: 1000 kB\nMemAvailable: 400 kB\nSwapTotal: 200 kB\nSwapFree: 150 kB\n"
    )
    monkeypatch.setattr("rdp.api.monitoring.PROC_ROOT", proc)
    ticks = iter([10.0, 12.0])
    monkeypatch.setattr("rdp.api.monitoring._monotonic", lambda: next(ticks))
    with job_api_case(tmp_path / "state") as case:
        case.login()
        assert case.client.get("/api/monitoring/resources").status_code == 200
        (proc / "net" / "dev").write_text("eth0: 3000 0 0 0 0 0 0 0 5000 0 0 0 0 0 0 0\n")
        (proc / "stat").write_text("cpu  160 0 70 870 0 0 0 0\n")
        response = case.client.get("/api/monitoring/resources")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["cpu_percent"] == 80.0
        assert result["memory_total_bytes"] == 1024000
        assert result["memory_available_bytes"] == 409600
        assert result["download_speed_bytes_per_s"] == 0
        assert result["history"][-1]["network"]["eth0"] == {
            "receive_bytes_per_s": 1000.0,
            "send_bytes_per_s": 1500.0,
        }
