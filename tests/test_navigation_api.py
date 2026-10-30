"""M1-07 Web 侧：导航层恢复失败标记的读取与管理员确认接口（用临时状态目录和数据库，不碰导航层）。"""

from datetime import UTC, datetime
from pathlib import Path

from account_api_support import add_actor
from jobs_api_support import job_api_case
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.infra.db.connection import session_scope
from rdp.jobs.navwrite.marker import is_navigation_write_blocked, record_recovery_block
from rdp.jobs.navwrite.models import MismatchItem
from rdp.jobs.navwrite.policy import MARKER_ITEM_SAMPLE_LIMIT

NOW = datetime(2026, 10, 29, 12, tzinfo=UTC)
BLOCK = "/api/navigation/recovery-block"
ACK = BLOCK + "/acknowledge"


def _item(job_id: int, step: int, path: str = "a.json") -> MismatchItem:
    return MismatchItem(
        job_id=job_id,
        step_index=step,
        path=path,
        expected_before="sha256 aaaaaaaaaaaa",
        expected_after="sha256 bbbbbbbbbbbb",
        actual="sha256 cccccccccccc",
    )


def test_unauthenticated_is_rejected(tmp_path: Path) -> None:
    """未登录读取和确认都是 401。"""
    with job_api_case(tmp_path) as case:
        assert case.client.get(BLOCK).status_code == 401
        assert case.client.post(ACK).status_code == 401


def test_read_without_marker(tmp_path: Path) -> None:
    """没有标记时返回 blocked=false，成员也能读。"""
    with job_api_case(tmp_path) as case:
        member = add_actor(case)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        response = case.client.get(BLOCK, headers=headers)
        assert response.status_code == 200
        assert response.json() == {"blocked": False}


def test_read_with_marker_and_sample_cap(tmp_path: Path) -> None:
    """有标记时带 set_at、作业编号文本、样例项和完整总数。"""
    with job_api_case(tmp_path) as case:
        total = MARKER_ITEM_SAMPLE_LIMIT + 5
        items = tuple(_item(3, i, f"d/{i}.json") for i in range(total))
        with session_scope(case.engine) as session:
            record_recovery_block(session, items, now=NOW)
        member = add_actor(case)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        body = case.client.get(BLOCK, headers=headers).json()
        assert body["blocked"] is True
        assert body["set_at"].startswith("2026-10-29T12:00:00")
        assert body["job_ids"] == ["3"]
        assert body["total_items"] == total
        assert len(body["items"]) == MARKER_ITEM_SAMPLE_LIMIT
        assert body["items"][0] == {
            "job_id": "3",
            "step_index": 0,
            "path": "d/0.json",
            "expected_before": "sha256 aaaaaaaaaaaa",
            "expected_after": "sha256 bbbbbbbbbbbb",
            "actual": "sha256 cccccccccccc",
        }


def test_member_cannot_acknowledge(tmp_path: Path) -> None:
    """成员确认返回 403，标记保留，不写日志。"""
    with job_api_case(tmp_path) as case:
        with session_scope(case.engine) as session:
            record_recovery_block(session, (_item(3, 0),), now=NOW)
        member = add_actor(case)
        headers = {"Cookie": "rdp_session=" + member.token.get_secret_value()}
        assert case.client.post(ACK, headers=headers).status_code == 403
        with session_scope(case.engine, read_only=True) as session:
            assert is_navigation_write_blocked(session)
            assert session.execute(select(OperationLogRow)).scalars().all() == [] or all(
                row.operation != "confirm_navigation_recovery"
                for row in session.execute(select(OperationLogRow)).scalars()
            )


def test_acknowledge_requires_same_origin(tmp_path: Path) -> None:
    """跨源 POST 在认证之前就是 403，标记保留。"""
    with job_api_case(tmp_path) as case:
        with session_scope(case.engine) as session:
            record_recovery_block(session, (_item(3, 0),), now=NOW)
        assert case.login().status_code == 200
        response = case.client.post(ACK, headers={"Origin": "http://evil.example"})
        assert response.status_code == 403
        with session_scope(case.engine, read_only=True) as session:
            assert is_navigation_write_blocked(session)


def test_admin_acknowledge_clears_and_audits(tmp_path: Path) -> None:
    """管理员确认：清标记、写 confirm_navigation_recovery，操作人是当前管理员。"""
    with job_api_case(tmp_path) as case:
        with session_scope(case.engine) as session:
            record_recovery_block(session, (_item(3, 0), _item(7, 1)), now=NOW)
        assert case.login().status_code == 200
        response = case.client.post(ACK)
        assert response.status_code == 200
        assert response.json() == {"cleared_job_ids": ["3", "7"]}
        assert case.client.get(BLOCK).json() == {"blocked": False}
        with session_scope(case.engine, read_only=True) as session:
            assert not is_navigation_write_blocked(session)
            rows = [
                row
                for row in session.execute(select(OperationLogRow)).scalars()
                if row.operation == "confirm_navigation_recovery"
            ]
        (row,) = rows
        assert row.actor_name == "管理员" and row.actor_id is not None
        assert row.result == "success"


def test_acknowledge_without_marker_is_conflict(tmp_path: Path) -> None:
    """没有标记时确认是 409，不写日志。"""
    with job_api_case(tmp_path) as case:
        assert case.login().status_code == 200
        response = case.client.post(ACK)
        assert response.status_code == 409
        assert response.json()["category"] == "conflict"
        with session_scope(case.engine, read_only=True) as session:
            assert session.execute(select(OperationLogRow)).scalars().all() == [] or all(
                row.operation != "confirm_navigation_recovery"
                for row in session.execute(select(OperationLogRow)).scalars()
            )


def test_navigation_api_import_boundary() -> None:
    """接口模块不 import 写导航层的模块。"""
    source = (Path(__file__).parents[1] / "src/rdp/api/navigation.py").read_text()
    for name in ("atomic", "recovery", "pipeline", "navwrite.jobs"):
        assert f"rdp.jobs.navwrite.{name.split('.')[-1]}" not in source
