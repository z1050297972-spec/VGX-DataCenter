"""重建索引命令验收；只通过公开命令与查询接口，全部输入属于临时目录。"""

import io
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from threading import Event

import pytest
from nav_manifest import FakeNavigation
from ops_support import runtime_inputs
from sqlalchemy import text, update

from rdp.audit.records import query_operations
from rdp.audit.types import LogQuery, OperationQuery
from rdp.infra.config import load_config
from rdp.infra.db.connection import create_database_engine, session_scope
from rdp.infra.state import state_paths
from rdp.infra.storage import LinuxMountSource
from rdp.jobs.dataset_browser.queries import (
    DatasetQueries,
    QueryAccess,
)
from rdp.jobs.datasets.index import read_index_baseline
from rdp.jobs.datasets.models import DatasetRow, EntryRow, LinkRow
from rdp.jobs.worker import worker_lock
from rdp.ops.cli import Console, run_cli
from rdp.ops.runtime import RuntimeInputs
from rdp.ops.status import check_worker_stopped


def _run(inputs: RuntimeInputs) -> tuple[int, str, str]:
    """调用真实解析与分派，捕获可供操作者使用的退出码及输出。"""
    stdout, stderr = io.StringIO(), io.StringIO()
    code = run_cli(
        ["rebuild-index"],
        inputs=inputs,
        console=Console(stdout, stderr, lambda _: ""),
        web=lambda _: 99,
        signals=lambda _: nullcontext(),
    )
    return code, stdout.getvalue(), stderr.getvalue()


def test_rebuild_refuses_running_worker(tmp_path: Path) -> None:
    """验证验收1：worker持锁时拒绝重建，非零退出并提示到网页提交。"""
    inputs = runtime_inputs(tmp_path)
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    lock = worker_lock(paths)
    try:
        code, stdout, stderr = _run(inputs)
        assert code == 1
        assert "网页" in stderr and "提交" in stderr
        assert "worker" in stderr
        assert stdout == ""
    finally:
        lock.finish(())


def _inputs(tmp_path: Path, nav: FakeNavigation) -> RuntimeInputs:
    """为真实CLI提供临时配置和合成NFS挂载表，不借用机器上的设备。"""
    inputs = runtime_inputs(tmp_path / "runtime")
    config = Path(inputs.environ["RDP_CONFIG"])
    config.write_text(
        'state_dir = "~/state"\nnav_root = '
        + json.dumps(str(nav.nav_root))
        + "\n[jobs]\ngpus = []\n"
        + "".join(
            "\n[[storage_roots]]\nname = "
            + json.dumps(root.name)
            + "\npath = "
            + json.dumps(str(root.path))
            + '\nnfs_export = "fixture:/'
            + root.name
            + '"\n'
            for root in nav.storage_roots
        )
    )
    (tmp_path / "runtime/mountinfo").write_text(
        "\n".join(
            f"{index + 1} 0 0:{index + 1} / {root.path} rw - nfs fixture:/{root.name} rw"
            for index, root in enumerate(nav.storage_roots)
        )
    )
    return inputs


def test_rebuild_runs_both_stages(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证验收1：空库重建得到五个样本、十个入口及真实存储检查，打印摘要。"""
    inputs = _inputs(tmp_path, fake_nav)
    code, stdout, stderr = _run(inputs)
    assert code == 0, stderr
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine, read_only=True) as session:
            baseline = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
        assert len(baseline) == 5
        assert sum(len(item.entry_paths) for item in baseline) == 10
        panel = DatasetQueries(engine, fake_nav.nav_root).panel(
            QueryAccess(inputs.clock.now(), lambda _: 1), None
        )
        assert len(panel.storage_roots) == 2
        assert all(root.online is True for root in panel.storage_roots)
        assert "5" in stdout and "10" in stdout and "重建" in stdout
    finally:
        engine.dispose()


def test_rebuild_holds_worker_lock(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证验收3：存储检查期间始终占用worker锁，命令完成后释放。"""
    inputs = _inputs(tmp_path, fake_nav)
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    original = LinuxMountSource.read_mountinfo
    observations: list[bool] = []

    def read_mountinfo(source: LinuxMountSource) -> str:
        observations.append(check_worker_stopped(paths.worker_lock).allowed)
        return original(source)

    monkeypatch.setattr(LinuxMountSource, "read_mountinfo", read_mountinfo)
    code, _, stderr = _run(inputs)
    assert code == 0, stderr
    assert observations and not any(observations)
    assert check_worker_stopped(paths.worker_lock).allowed


def test_rebuild_clears_corrupt_index(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证验收3：清空后从事实来源重建，不尝试复用已损坏的旧指纹。"""
    inputs = _inputs(tmp_path, fake_nav)
    assert _run(inputs)[0] == 0
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine, read_only=True) as session:
            expected = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
        # 损坏数据库是测试输入；恢复结果通过公开索引读取检查，不窥探实现的DELETE语句。
        with session_scope(engine) as session:
            session.execute(update(DatasetRow).values(fingerprint={"corrupt": True}))
        code, _, stderr = _run(inputs)
        assert code == 0, stderr
        with session_scope(engine, read_only=True) as session:
            assert read_index_baseline(session, None, nav_root=fake_nav.nav_root) == expected
    finally:
        engine.dispose()


def test_rebuild_records_one_ops_log(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证验收1：成功只记一条重建操作，操作者为运维，且可从日志查询接口读出。"""
    inputs = _inputs(tmp_path, fake_nav)
    code, _, stderr = _run(inputs)
    assert code == 0, stderr
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        with session_scope(engine, read_only=True) as session:
            page = query_operations(
                session, OperationQuery(LogQuery()), lambda _session, _ids: frozenset()
            )
        assert len(page.items) == 1
        event = page.items[0].event
        assert event.actor.account_id is None and event.actor.name == "运维"
        assert event.operation.value == "rebuild_index"
        assert event.target.kind == "dataset_index"
        assert event.result.value == "success"
    finally:
        engine.dispose()


def test_rebuild_drops_sizes_and_prints_next_step(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证验收3：旧统计值清空且不重新遍历；明确提示每晚或页面手动统计。"""
    inputs = _inputs(tmp_path, fake_nav)
    assert _run(inputs)[0] == 0
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        # 独立的旧统计输入，不能把缺统计的空库误当作清空旧大小的证据。
        with session_scope(engine) as session:
            for model in (DatasetRow, LinkRow):
                session.execute(
                    update(model).values(size_bytes=123, size_checked_at=inputs.clock.now())
                )
            session.execute(
                update(EntryRow).values(
                    size_bytes=123,
                    size_checked_at=inputs.clock.now(),
                    aria2_count=0,
                    incomplete_count=0,
                )
            )
        code, stdout, stderr = _run(inputs)
        assert code == 0, stderr
        assert "统计大小" in stdout and "每晚" in stdout and "页面" in stdout and "手动" in stdout
        detail = DatasetQueries(engine, fake_nav.nav_root).detail(
            QueryAccess(inputs.clock.now(), lambda _: 1), "按任务/libero_10"
        )
        assert detail.dataset_size.size_bytes is None
        assert all(
            link.size_bytes is None and link.size_checked_at is None for link in detail.links
        )
    finally:
        engine.dispose()


def test_rebuild_scan_failure_is_audited(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """验证失败契约：清空后导航不可读，非零退出、记录失败并释放锁，可修复后重跑。"""
    inputs = _inputs(tmp_path, fake_nav)
    assert _run(inputs)[0] == 0

    hidden = fake_nav.nav_root.with_name("temporarily-hidden-nav")
    fake_nav.nav_root.rename(hidden)
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    try:
        code, stdout, stderr = _run(inputs)
        assert code == 1 and "重建索引完成" not in stdout and stderr
        assert "索引现在是空的，修好原因后重跑" in stdout + stderr
        assert check_worker_stopped(paths.worker_lock).allowed
        with session_scope(engine, read_only=True) as session:
            assert read_index_baseline(session, None, nav_root=fake_nav.nav_root) == ()
            page = query_operations(
                session, OperationQuery(LogQuery()), lambda _session, _ids: frozenset()
            )
        assert len(page.items) == 2
        assert page.items[0].event.result.value == "failure"
        assert page.items[0].event.actor.name == "运维"
    finally:
        hidden.rename(fake_nav.nav_root)
        engine.dispose()
    assert _run(inputs)[0] == 0


def test_rebuild_lock_race(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """验证后半段：重建停留在第二段时真实worker入口非阻塞拒绝，随后重建完成并释放锁。"""
    inputs = _inputs(tmp_path, fake_nav)
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    entered, release = Event(), Event()
    original = LinuxMountSource.read_mountinfo

    def blocked_mountinfo(source: LinuxMountSource) -> str:
        entered.set()
        if not release.wait(timeout=5):
            raise TimeoutError("测试未按时释放挂载表读取")
        return original(source)

    def stopped_signals(stop: Event):
        # 若worker意外获得锁，也让它有限退出；退出0会使测试失败，不留下循环线程。
        stop.set()
        return nullcontext()

    monkeypatch.setattr(LinuxMountSource, "read_mountinfo", blocked_mountinfo)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(_run, inputs)
        try:
            assert entered.wait(timeout=5)
            code = run_cli(
                ["worker", "--no-stderr"],
                inputs=inputs,
                console=Console(io.StringIO(), io.StringIO(), lambda _: ""),
                web=lambda _: 99,
                signals=stopped_signals,
            )
            assert code == 2
            assert "另一个 worker 正在运行" in (paths.logs / "worker.log").read_text()
            assert not future.done()
        finally:
            release.set()
            result = future.result(timeout=5)
    assert result[0] == 0, result[2]
    assert check_worker_stopped(paths.worker_lock).allowed


@pytest.mark.parametrize("failure", ["publication", "audit"])
def test_rebuild_publication_failure(
    tmp_path: Path, fake_nav: FakeNavigation, failure: str
) -> None:
    """验证后半段：发布或成功审计SQL失败，旧索引（含大小）保留且只补一条失败日志。"""
    inputs = _inputs(tmp_path, fake_nav)
    assert _run(inputs)[0] == 0
    paths = state_paths(load_config(environ=inputs.environ, home=inputs.home).config, ())
    engine = create_database_engine(paths.database)
    queries = DatasetQueries(engine, fake_nav.nav_root)
    access = QueryAccess(inputs.clock.now(), lambda _: 1)
    try:
        with session_scope(engine) as session:
            session.execute(
                update(DatasetRow).values(size_bytes=123, size_checked_at=inputs.clock.now())
            )
        with session_scope(engine, read_only=True) as session:
            baseline = read_index_baseline(session, None, nav_root=fake_nav.nav_root)
        old_panel = queries.panel(access, None)
        old_size = queries.detail(access, "按任务/libero_10").dataset_size
        # 在SQLite真实写入边界制造故障，不替换发布函数或审计函数。
        trigger = (
            "CREATE TRIGGER fail_rebuild BEFORE INSERT ON dataset_scans "
            "BEGIN SELECT RAISE(ABORT, 'publication unavailable'); END"
            if failure == "publication"
            else "CREATE TRIGGER fail_rebuild BEFORE INSERT ON operation_logs "
            "WHEN NEW.operation='rebuild_index' AND NEW.result='success' "
            "BEGIN SELECT RAISE(ABORT, 'audit unavailable'); END"
        )
        with session_scope(engine) as session:
            session.execute(text(trigger))
        code, stdout, stderr = _run(inputs)
        assert code == 1 and stderr and "重建索引完成" not in stdout
        assert check_worker_stopped(paths.worker_lock).allowed
        with session_scope(engine) as session:
            session.execute(text("DROP TRIGGER fail_rebuild"))
        with session_scope(engine, read_only=True) as session:
            assert read_index_baseline(session, None, nav_root=fake_nav.nav_root) == baseline
            page = query_operations(
                session, OperationQuery(LogQuery()), lambda _s, _ids: frozenset()
            )
        assert queries.panel(access, None) == old_panel
        assert queries.detail(access, "按任务/libero_10").dataset_size == old_size
        assert len(page.items) == 2
        assert page.items[0].event.result.value == "failure"
        assert page.items[0].event.actor.name == "运维"
        assert page.items[1].event.result.value == "success"
    finally:
        engine.dispose()
