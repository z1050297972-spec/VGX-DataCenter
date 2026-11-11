"""M4-02 真伪终端执行验收；程序、工作目录、数据库和日志全部来自临时目录。"""

import os
import sys
import time
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest
from jobs_execution_support import execution_case
from jobs_process_resources import adopt_orphans, reap_known

from rdp.infra.diagnostics import ExternalError
from rdp.jobs.errors import JobCancelledError
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.processes import ToolCommand, run_terminal_process
from rdp.jobs.terminal import create_terminal_parser
from rdp.jobs.types import JobClock, JobProgress


@pytest.mark.parametrize("worker_term", [None, "dumb"])
def test_terminal_progress_and_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, worker_term: str | None
) -> None:
    """假工具收到固定TERM和GPU环境，父环境不变；TTY进度入库且日志不含重画字节。"""
    if worker_term is None:
        monkeypatch.delenv("TERM", raising=False)
    else:
        monkeypatch.setenv("TERM", worker_term)
    parent_environment = dict(os.environ)
    script = tmp_path / "tool.py"
    script.write_text(
        """import os, sys
assert sys.stdin.read() == ""
print("stdout 原样输出", flush=True)
assert os.get_terminal_size(2) == (200, 50)
assert os.environ.get("TERM") == "xterm-256color"
assert os.environ["CUDA_VISIBLE_DEVICES"] == "1"
assert os.environ["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
if sys.stderr.isatty():
    sys.stderr.write("\\r\\x1b[2Khead_left [===] 3/3 帧  完成\\n完成：测试\\n")
""",
        encoding="utf-8",
    )

    def execute(context: ExecutionContext) -> None:
        assert (
            run_terminal_process(
                ToolCommand("假转换", (sys.executable, str(script)), tmp_path, 5),
                context.reporter,
                context.log,
                context.clock,
                gpu_index=1,
                parser=create_terminal_parser("mcap2lerobot-pty", stage_count=3, first_stage=1),
            )
            == 0
        )

    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        result = execute_job(work, deps, signals)
        assert result is not None and result.summary is not None
        assert result.summary.tool_exit_code == 0
        assert result.progress is not None and result.progress.parts[0].done == 3
        assert result.progress.parts[0].total == 3
        assert result.log_path is not None
        text = (deps.paths.root / result.log_path).read_text()
        assert "stdout 假转换│stdout 原样输出" in text
        assert "stderr 假转换│完成：测试" in text
        assert "\x1b" not in text and "[===]" not in text
        assert all(not thread.is_alive() for thread in signals.monitor.threads)
        assert dict(os.environ) == parent_environment


def test_no_progress_preserves_precheck_snapshot(tmp_path: Path) -> None:
    """评审回归：工具30秒无可解析进度时保留核对输入阶段和全部计数，只增加一次警告。"""
    script, release = tmp_path / "silent.py", tmp_path / "release"
    script.write_text(
        """import pathlib, sys, time
sys.stderr.write("就绪\\n")
sys.stderr.flush()
deadline = time.monotonic() + 5
while not pathlib.Path("release").exists() and time.monotonic() < deadline:
    time.sleep(0.01)
""",
        encoding="utf-8",
    )
    baseline = JobProgress(
        stage_index=2,
        stage_count=5,
        stage_name="核对输入",
        done=7,
        total=9,
        unit="文件",
        total_items=7,
        failed_items=1,
        warning_count=2,
    )
    advanced, stop = Event(), Event()

    def execute(context: ExecutionContext) -> None:
        context.reporter.report(baseline)

        def advance_after_output() -> None:
            deadline = time.monotonic() + 3
            try:
                # 看到终端读线程写出的文本后再推进时钟，避免把31秒跳变算到初始化之前。
                while "stderr 静默工具│就绪" not in log_path.read_text():
                    if time.monotonic() >= deadline or stop.wait(0.01):
                        return
                advanced.set()
                while time.monotonic() < deadline:
                    progress = context.reporter.snapshot().progress
                    if progress is not None and progress.warning_count == 3:
                        return
                    if stop.wait(0.01):
                        return
            finally:
                release.touch()

        thread = Thread(target=advance_after_output, daemon=True)
        try:
            thread.start()
            run_terminal_process(
                ToolCommand("静默工具", (sys.executable, str(script)), tmp_path, 60),
                context.reporter,
                context.log,
                context.clock,
                parser=create_terminal_parser("mcap2lerobot-pty", stage_count=5, first_stage=3),
            )
        finally:
            stop.set()
            release.touch()
            thread.join(timeout=4)
            assert not thread.is_alive()

    with execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
        work,
        deps,
        signals,
    ):
        assert work.record.log_path is not None
        log_path = deps.paths.root / work.record.log_path
        clock = JobClock(
            deps.clock.now, lambda: time.monotonic() + (31 if advanced.is_set() else 0)
        )
        result = execute_job(work, replace(deps, clock=clock), signals)
        assert result is not None and result.summary is not None
        assert result.summary.tool_exit_code == 0
        assert result.progress == baseline.model_copy(update={"warning_count": 3})
        assert len(result.diagnostics) == 1 and result.diagnostics[0].warning_count == 1
        assert all(not thread.is_alive() for thread in signals.monitor.threads)


@pytest.mark.parametrize("ending", ["cancel", "timeout"])
def test_terminal_cancellation_and_timeout(tmp_path: Path, ending: str) -> None:
    """验收4：取消传播原取消异常，超时为外部失败；两者均保存退出码并回收进程组和输出线程。"""
    ready = tmp_path / "ready"
    script = tmp_path / "blocked.py"
    script.write_text(
        """import os, pathlib, subprocess, sys, time
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
pathlib.Path("ready").write_text(f"{os.getpid()} {child.pid}")
if sys.stderr.isatty():
    sys.stderr.write("head_left [==] 2/10 帧\\n")
    sys.stderr.flush()
time.sleep(30)
""",
        encoding="utf-8",
    )
    caught: list[Exception] = []

    def execute(context: ExecutionContext) -> None:
        error_type = JobCancelledError if ending == "cancel" else ExternalError
        with pytest.raises(error_type) as error:
            run_terminal_process(
                ToolCommand(
                    "阻塞工具",
                    (sys.executable, str(script)),
                    tmp_path,
                    5 if ending == "cancel" else 0.5,
                ),
                context.reporter,
                context.log,
                context.clock,
                parser=create_terminal_parser("mcap2lerobot-pty", stage_count=2, first_stage=1),
            )
        caught.append(error.value)

    with (
        adopt_orphans(),
        execution_case(tmp_path / "state", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            deps,
            signals,
        ),
    ):
        stop = Event()

        def cancel_when_ready() -> None:
            deadline = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < deadline:
                if stop.wait(0.01):
                    return
            if ending == "cancel":
                signals.cancelled.set()

        thread = Thread(target=cancel_when_ready, daemon=True)
        try:
            thread.start()
            result = execute_job(work, deps, signals)
            assert len(caught) == 1
            assert result is not None and result.summary is not None
            assert result.summary.tool_exit_code is not None and result.summary.tool_exit_code < 0
            if ending == "timeout":
                assert isinstance(caught[0], ExternalError)
                assert "timeout_s" in caught[0].diagnostics[0].actual
            assert all(not item.is_alive() for item in signals.monitor.threads)
            # 先观察生产清理结果再由夹具兜底；不能用夹具kill制造“已回收”的假象。
            parent, child = map(int, ready.read_text().split())
            reap_known(child)
            for pid in (parent, child):
                with pytest.raises(ProcessLookupError):
                    os.kill(pid, 0)
        finally:
            stop.set()
            thread.join(timeout=4)
            if ready.exists():
                for pid in map(int, ready.read_text().split()):
                    reap_known(pid, kill=True)
            assert not thread.is_alive()
