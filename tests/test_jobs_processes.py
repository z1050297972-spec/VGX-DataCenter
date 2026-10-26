"""08验收2/3/4真实进程场景；隔离进程组，finally清理工具后代并恢复subreaper状态。"""

import os
import signal
import subprocess
import sys
import time
from collections.abc import Generator
from pathlib import Path

import pytest
from job_process_support import (
    CANCEL_MAX_ELAPSED_S,
    CANCEL_MIN_ELAPSED_S,
    PROCESS_EXIT_TIMEOUT_S,
    PROCESS_READY_TIMEOUT_S,
    PROCESS_STOP_TIMEOUT_S,
    prepare_process_case,
)
from jobs_process_resources import adopt_orphans

from rdp.jobs.policy import WORKER_EXIT_ALREADY_RUNNING, WORKER_EXIT_FAILURE, WORKER_EXIT_OK
from rdp.jobs.processes import ToolCommand
from rdp.jobs.types import JobState


@pytest.fixture(autouse=True)
def _own_tool_orphans() -> Generator[None]:
    """测试接管被SIGKILL的worker留下的工具，交既有cleanup_orphans逐PID回收。"""
    with adopt_orphans():
        yield


@pytest.mark.parametrize("mode", ["resume", "restart", "interrupt"])
def test_sigkill_recovery(mode: str, tmp_path: Path) -> None:
    """验收3：真实worker在已落库进度握手后SIGKILL，重启按三种方式恢复，中断段逐项等于旧进度。"""
    case = prepare_process_case(tmp_path, mode)
    runner = Path(__file__).with_name("job_worker_process.py")
    second: subprocess.Popen[bytes] | None = None
    # 只运行当前解释器与仓库内固定夹具，无shell、不拼接用户命令。
    first = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
        [sys.executable, str(runner), str(tmp_path), mode], start_new_session=True
    )
    try:
        before = case.wait_running(PROCESS_READY_TIMEOUT_S)
        first.send_signal(signal.SIGKILL)
        assert first.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == -signal.SIGKILL
        # 第二实例是新的操作系统进程，不能用同一对象调用恢复函数冒充崩溃恢复。
        second = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
            [sys.executable, str(runner), str(tmp_path), mode], start_new_session=True
        )
        after = case.wait_terminal(PROCESS_READY_TIMEOUT_S)
        logged_progress, handling = case.interruption()
        assert (logged_progress, handling) == (before.progress, mode)
        assert (after.started_at, after.job_id, after.log_path) == (
            before.started_at,
            before.job_id,
            before.log_path,
        )
        if mode == "interrupt":
            assert (after.state, after.progress, case.execution_modes()) == (
                JobState.INTERRUPTED,
                before.progress,
                ("fresh",),
            )
            assert after.summary is not None and after.summary.outcome is None
        else:
            assert after.state is JobState.COMPLETED
            assert case.execution_modes() == ("fresh", mode)
            previous, initial = case.resumed_progress()
            assert previous == before.progress
            if mode == "resume":
                assert initial == before.progress
            else:
                assert initial is None or initial.total_items == 0
            case.wait_queued_terminal(PROCESS_READY_TIMEOUT_S)
            assert case.execution_order() == (case.job_id, case.job_id, case.queued_job_id)
        case.stop()
        assert second.wait(timeout=PROCESS_READY_TIMEOUT_S) == WORKER_EXIT_OK
    finally:
        try:
            for process in (second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            # wait超时也必须进入夹具清理，不能让异常跳过孤儿工具及其余worker。
            case.cleanup_orphans()


def test_second_worker_lock(tmp_path: Path) -> None:
    """验收2：两个真实worker进程共用临时状态目录，第二个返回具名锁竞争码且日志含锁路径。"""
    case = prepare_process_case(tmp_path, "lock")
    runner = Path(__file__).with_name("job_worker_process.py")
    second: subprocess.Popen[bytes] | None = None
    # 当前解释器和固定测试入口；没有shell或外部输入。
    first = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
        [sys.executable, str(runner), str(tmp_path), "lock"], start_new_session=True
    )
    try:
        case.wait_running(PROCESS_READY_TIMEOUT_S)
        # 第二个真实进程必须被flock拒绝，不能靠模块级变量模拟单实例。
        second = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
            [sys.executable, str(runner), str(tmp_path), "lock"], start_new_session=True
        )
        assert second.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == WORKER_EXIT_ALREADY_RUNNING
        log = (tmp_path / "logs" / "worker.log").read_text()
        assert "另一个 worker 正在运行" in log
        assert str(tmp_path / "worker.lock") in log
    finally:
        try:
            for process in (second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            # wait超时也必须进入夹具清理，不能让异常跳过孤儿工具及其余worker。
            case.cleanup_orphans()


def test_lock_not_inherited(tmp_path: Path) -> None:
    """锁继承：真实worker启动长工具后被SIGKILL，孤儿工具仍活着时第二worker能拿锁。"""
    case = prepare_process_case(tmp_path, "lock_inheritance")
    runner = Path(__file__).with_name("job_worker_process.py")
    second: subprocess.Popen[bytes] | None = None
    # 可信本地解释器及夹具，隔离进程组方便finally清理。
    first = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
        [sys.executable, str(runner), str(tmp_path), "lock_inheritance"], start_new_session=True
    )
    try:
        case.wait_running(PROCESS_READY_TIMEOUT_S)
        case.wait_tool_ready(PROCESS_READY_TIMEOUT_S)
        tool_pid = case.tool_pid()
        first.kill()
        first.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        os.kill(tool_pid, 0)
        # 保持孤儿进程活着再启动，否则无法发现flock描述符继承缺陷。
        second = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
            [sys.executable, str(runner), str(tmp_path), "lock_inheritance"], start_new_session=True
        )
        case.wait_terminal(PROCESS_READY_TIMEOUT_S)
        assert second.poll() is None
        case.stop()
        assert second.wait(timeout=PROCESS_READY_TIMEOUT_S) == WORKER_EXIT_OK
    finally:
        try:
            for process in (second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            # wait超时也必须进入夹具清理，不能让异常跳过孤儿工具及其余worker。
            case.cleanup_orphans()


def test_external_process_ignores_sigterm(tmp_path: Path) -> None:
    """验收4：测试类型用sys.executable启动真实忽略SIGTERM工具，取消约10秒后SIGKILL、状态已取消无结果。"""
    tool_code = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('ready', flush=True); time.sleep(60)"
    command = ToolCommand("忽略终止测试", (sys.executable, "-u", "-c", tool_code), tmp_path, 60.0)
    case = prepare_process_case(tmp_path, "term_ignored", command)
    runner = Path(__file__).with_name("job_worker_process.py")
    # 可信测试脚本，其执行函数通过生产外部进程入口启动上面的Python工具。
    worker = subprocess.Popen(  # noqa: S603  # 理由：仅当前解释器和仓库固定测试入口，无 shell。
        [sys.executable, str(runner), str(tmp_path), "term_ignored"], start_new_session=True
    )
    try:
        case.wait_running(PROCESS_READY_TIMEOUT_S)
        case.wait_tool_ready(PROCESS_READY_TIMEOUT_S)
        started = time.monotonic()
        case.request_cancel()
        ended = case.wait_terminal(CANCEL_MAX_ELAPSED_S)
        elapsed_s = time.monotonic() - started
        assert CANCEL_MIN_ELAPSED_S <= elapsed_s <= CANCEL_MAX_ELAPSED_S
        assert ended.state is JobState.CANCELLED
        assert ended.summary is not None
        assert ended.summary.outcome is None
        assert ended.summary.tool_exit_code == -signal.SIGKILL
        case.stop()
        assert worker.wait(timeout=PROCESS_READY_TIMEOUT_S) == WORKER_EXIT_OK
    finally:
        try:
            if worker.poll() is None:
                worker.kill()
            worker.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            case.cleanup_orphans()


def test_shutdown_timeout_keeps_lock_until_process_exit(tmp_path: Path) -> None:
    """第2条：真实worker超时返回失败但进程尚活时第二实例锁失败，第一进程退出后才允许新实例持锁。"""
    case = prepare_process_case(tmp_path, "shutdown_timeout")
    runner = Path(__file__).with_name("job_worker_process.py")
    second: subprocess.Popen[bytes] | None = None
    third: subprocess.Popen[bytes] | None = None
    first = subprocess.Popen(  # noqa: S603  # 理由：只运行当前解释器和固定本地测试入口。
        [sys.executable, str(runner), str(tmp_path), "shutdown_timeout"], start_new_session=True
    )
    try:
        case.wait_running(PROCESS_READY_TIMEOUT_S)
        case.stop()
        result = case.wait_worker_return(PROCESS_STOP_TIMEOUT_S)
        assert (result.code, result.lock_retained, first.poll()) == (
            WORKER_EXIT_FAILURE,
            True,
            None,
        )
        second = subprocess.Popen(  # noqa: S603  # 理由：本地第二实例验证真实flock，不执行shell。
            [sys.executable, str(runner), str(tmp_path), "lock"], start_new_session=True
        )
        assert second.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == WORKER_EXIT_ALREADY_RUNNING
        case.allow_process_exit()
        assert first.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == WORKER_EXIT_FAILURE
        third = subprocess.Popen(  # noqa: S603  # 理由：固定夹具验证原进程退出后锁自然释放。
            [sys.executable, str(runner), str(tmp_path), "lock"], start_new_session=True
        )
        case.wait_terminal(PROCESS_READY_TIMEOUT_S)
        assert third.poll() is None
    finally:
        try:
            for process in (third, second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            case.cleanup_orphans()


def test_crash_after_claim_before_log_header(tmp_path: Path) -> None:
    """第4条：真实worker在领取提交但日志未建时SIGKILL，重启沿已登记路径先写头再中断，领取时间不变。"""
    case = prepare_process_case(tmp_path, "claim_gap")
    runner = Path(__file__).with_name("job_worker_process.py")
    second: subprocess.Popen[bytes] | None = None
    first = subprocess.Popen(  # noqa: S603  # 理由：仅本地解释器和固定领取窗口测试夹具。
        [sys.executable, str(runner), str(tmp_path), "claim_gap"], start_new_session=True
    )
    try:
        before = case.wait_claimed_before_log(PROCESS_READY_TIMEOUT_S)
        assert before.state is JobState.RUNNING and before.log_path is not None
        assert not (tmp_path / before.log_path).exists()
        first.kill()
        assert first.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == -signal.SIGKILL
        second = subprocess.Popen(  # noqa: S603  # 理由：真实新进程验证已登记路径的中断恢复。
            [sys.executable, str(runner), str(tmp_path), "interrupt"], start_new_session=True
        )
        after = case.wait_terminal(PROCESS_READY_TIMEOUT_S)
        assert (after.started_at, after.log_path, after.state) == (
            before.started_at,
            before.log_path,
            JobState.INTERRUPTED,
        )
        assert case.log_section_order() == ("header", "interruption", "summary")
        case.stop()
        assert second.wait(timeout=PROCESS_STOP_TIMEOUT_S) == WORKER_EXIT_OK
    finally:
        try:
            for process in (second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            case.cleanup_orphans()
