"""镜像状态经下载探测后保存，测试传输不联网。"""

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from rdp.jobs.downloads.plan import HttpResponse
from rdp.monitoring.mirror import check_mirror, latest_mirror


class _Transport:
    """按测试指定的 HTTP 响应或超时返回。"""

    def __init__(self, status: int | None) -> None:
        self.status = status

    def request(
        self, method: str, url: str, *, headers: Mapping[str, str], timeout_s: float
    ) -> HttpResponse:
        if self.status is None:
            raise TimeoutError
        return HttpResponse(self.status, {"Location": "https://huggingface.co/"}, b"")


@pytest.mark.parametrize(
    "http_status, expected", [(308, "ineffective"), (200, "effective"), (None, "unknown")]
)
def test_mirror_result_saved(http_status: int | None, expected: str) -> None:
    """308、200 和超时分别保存不生效、生效和未知及检查时间。"""
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE monitoring_mirror (id INTEGER PRIMARY KEY, status TEXT NOT NULL, checked_at TEXT NOT NULL)"
        )
    now = datetime(2026, 11, 1, tzinfo=UTC)
    check_mirror(engine, _Transport(http_status), now=now, sleep=lambda _: None)
    result = latest_mirror(engine)
    assert result is not None
    assert result.status == expected
    assert result.checked_at == now


def test_worker_periodic_and_manual_checks_without_jobs(tmp_path: Path) -> None:
    """Worker 每 60 秒检查，手动请求立即检查且不写作业表。"""
    from threading import Event

    from jobs_api_support import job_api_case

    from rdp.jobs.types import JobClock
    from rdp.monitoring.periodic import MirrorMonitor

    with job_api_case(tmp_path) as case:
        case.login()
        seconds = [0.0]
        transport = _Transport(200)
        monitor = MirrorMonitor(
            case.engine,
            transport,
            JobClock(lambda: case.clock.value, lambda: seconds[0]),
            collect=lambda _checkpoint: None,
        )
        stop = Event()
        assert monitor.tick(stop) is True
        seconds[0] = 59.0
        assert monitor.tick(stop) is False
        assert case.client.post("/api/monitoring/mirror/check").status_code == 202
        assert monitor.tick(stop) is True
        assert monitor.tick(stop) is False
        seconds[0] = 119.0
        assert monitor.tick(stop) is True
        with case.engine.connect() as connection:
            assert connection.execute(text("SELECT count(*) FROM jobs")).scalar_one() == 0
            row = connection.execute(
                text("SELECT requested_seq, completed_seq FROM monitoring_mirror")
            ).one()
            assert row == (1, 1)
