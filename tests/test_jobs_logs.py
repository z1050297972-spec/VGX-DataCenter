"""作业日志公共边界测试；只访问临时状态目录，断言文件内容与数据库快照。"""

import json
import sys
from dataclasses import replace
from datetime import timedelta, timezone
from pathlib import Path
from threading import Thread
from typing import IO, cast

import pytest
from jobs_execution_support import execution_case
from jobs_progress_support import saved_record
from jobs_storage_support import NOW, PROGRESS, job_database, job_row
from pydantic import TypeAdapter

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import (
    DefectError,
    Diagnostic,
    DiagnosticCategory,
    DiagnosticLevel,
    DiagnosticObject,
    ExternalError,
    render_diagnostic,
)
from rdp.jobs.execution import ExecutionContext, execute_job, recover_job
from rdp.jobs.logs import JobLog, JobLogMetadata, open_job_log, read_log_tail
from rdp.jobs.processes import ToolCommand
from rdp.jobs.records import claim_job, find_job
from rdp.jobs.types import JobProgress, JobRecord, JobState, JobSummary, RecoveryMode

EMPTY_METADATA = JobLogMetadata(None, None, None)


def test_header_metadata(tmp_path: Path) -> None:
    """验收7：开头含编号/稳定键/显示名/提交人/参数，配置哈希/工具版本/协议版本有值才写。"""
    with job_database(tmp_path) as (engine, paths):
        with session_scope(engine) as session:
            session.add(job_row())
        with session_scope(engine, read_only=True) as session:
            record = find_job(session, 71)
        log, needs_header = open_job_log(paths, record)
        assert needs_header and record.log_path is not None
        target = paths.root / record.log_path
        try:
            log.write_header(record, EMPTY_METADATA)
            first = target.read_text()
            assert "job_id=71" in first and "example_count" in first and "示例：数数" in first
            assert '"account_id": 7' in first and "历史提交人" in first
            assert '"steps": 4' in first and '"interval_ms": 0' in first
            assert "configuration=" not in first and "tool_version=" not in first
            assert "protocol_version=" not in first
            log.write_header(record, JobLogMetadata("hash=abc", "tool commit1", "v1"))
            content = target.read_text()
            assert "configuration=hash=abc" in content
            assert "tool_version=tool commit1" in content and "protocol_version=v1" in content
            for metadata in (
                JobLogMetadata("x" * 16385, None, None),
                JobLogMetadata(None, "x" * 257, None),
            ):
                with pytest.raises(DefectError):
                    log.write_header(record, metadata)
            with pytest.raises(DefectError):
                log.write_header(replace(record, started_at=None), EMPTY_METADATA)
        finally:
            log.close()
        with pytest.raises(DefectError):
            log.write_header(record, EMPTY_METADATA)


def test_utc_filename(tmp_path: Path) -> None:
    """日志命名：UTC毫秒格式不受本机时区影响，数据库存相对logs路径，恢复追加同文件。"""
    with job_database(tmp_path) as (engine, paths):
        with session_scope(engine) as session:
            session.add(job_row(JobState.QUEUED))
        with session_scope(engine) as session:
            record = claim_job(
                session,
                71,
                now=NOW.astimezone(timezone(timedelta(hours=-6))),
                paths=paths,
                gpu_index=None,
            )
        assert record.log_path == "logs/示例：数数/2026-10-26_120000_000.log"
        log, needs_header = open_job_log(paths, record)
        try:
            assert needs_header
            log.write_header(record, EMPTY_METADATA)
        finally:
            log.close()
        log, needs_header = open_job_log(paths, record)
        try:
            assert not needs_header
            log.write_line("继续", now=NOW.astimezone(timezone(timedelta(hours=8))))
        finally:
            log.close()
        content = (paths.root / record.log_path).read_text()
        assert "job_id=71" in content and "2026-10-26T12:00:00Z 继续" in content


def test_millisecond_collision(tmp_path: Path) -> None:
    """日志命名：同类型同毫秒在领取事务中按已登记路径/既有文件避让，第二作业用编号后缀；唯一约束防重名，恢复不重新命名。"""
    with job_database(tmp_path) as (engine, paths):
        with session_scope(engine) as session:
            session.add_all([job_row(JobState.QUEUED, job_id=i) for i in (71, 72, 73)])
        records: list[JobRecord] = []
        for job_id in (71, 72):
            with session_scope(engine) as session:
                records.append(claim_job(session, job_id, now=NOW, paths=paths, gpu_index=None))
        assert [r.log_path for r in records] == [
            "logs/示例：数数/2026-10-26_120000_000.log",
            "logs/示例：数数/2026-10-26_120000_000_72.log",
        ]
        existing = paths.logs / "示例：数数/2026-10-26_120001_000.log"
        existing.write_text("历史文件\n")
        with session_scope(engine) as session:
            third = claim_job(
                session, 73, now=NOW + timedelta(seconds=1), paths=paths, gpu_index=None
            )
        assert third.log_path == "logs/示例：数数/2026-10-26_120001_000_73.log"
        for record in records + [third]:
            log, needs_header = open_job_log(paths, record)
            try:
                assert needs_header
                log.write_header(record, EMPTY_METADATA)
            finally:
                log.close()
        assert existing.read_text() == "历史文件\n"


def test_summary_matches_record(tmp_path: Path) -> None:
    """验收7：逐项比较日志与数据库的state/outcome/progress/total_items/failed_items/warning_count/aborted/elapsed_s/artifacts/tool_exit_code。"""
    with job_database(tmp_path) as (engine, paths):
        with session_scope(engine) as session:
            session.add(job_row(JobState.COMPLETED))
        with session_scope(engine, read_only=True) as session:
            record = find_job(session, 71)
        assert record.summary is not None and record.log_path is not None
        log, _ = open_job_log(paths, record)
        try:
            log.write_summary(record.summary, now=NOW)
        finally:
            log.close()
        text = (paths.root / record.log_path).read_text()
        saved = json.loads(text.split("summary=", 1)[1])
        assert saved == TypeAdapter(JobSummary).dump_python(record.summary, mode="json")
        assert saved == {
            "state": "completed",
            "outcome": "partially_succeeded",
            "progress": {
                "stage_index": 1,
                "stage_count": 2,
                "stage_name": "处理",
                "done": 2,
                "total": 4,
                "unit": "条",
                "total_items": 2,
                "failed_items": 1,
                "warning_count": 3,
            },
            "total_items": 2,
            "failed_items": 1,
            "warning_count": 3,
            "aborted": False,
            "elapsed_s": 2.5,
            "artifacts": ["产物/样例"],
            "tool_exit_code": 0,
        }
        log, _ = open_job_log(paths, record)
        try:
            for summary in (
                replace(record.summary, state=JobState.RUNNING),
                replace(record.summary, total_items=3),
            ):
                with pytest.raises(DefectError):
                    log.write_summary(summary, now=NOW)
        finally:
            log.close()


def test_thread_lines(tmp_path: Path) -> None:
    """验收7：执行和stdout/stderr读线程并发写，整行不互相穿插，每行写后刷新。"""
    target = tmp_path / "concurrent.log"
    log = JobLog(target)
    failures: list[BaseException] = []

    def writer(label: str) -> None:
        try:
            for index in range(40):
                log.write_line(f"{label}:{index}:" + "字" * 512, now=NOW)
        except BaseException as error:
            failures.append(error)

    threads = [
        Thread(target=writer, args=(label,), daemon=True) for label in ("执行", "stdout", "stderr")
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        assert not any(thread.is_alive() for thread in threads) and not failures
        # 仍未关闭就能读全，验证每次写后刷新，而非碰巧close时刷出。
        lines = target.read_text().splitlines()
        assert len(lines) == 120
        assert set(lines) == {
            f"2026-10-26T12:00:00Z {label}:{index}:" + "字" * 512
            for label in ("执行", "stdout", "stderr")
            for index in range(40)
        }
        with pytest.raises(DefectError):
            log.write_line("x" * 65537, now=NOW)
        with pytest.raises(DefectError):
            log.write_line("非法时刻", now=NOW.replace(tzinfo=None))
    finally:
        try:
            for thread in threads:
                if thread.ident is not None:
                    thread.join(timeout=3)
        finally:
            log.close()


def test_output_prefixes(tmp_path: Path) -> None:
    """验收7：stdout与stderr各行有stdout 工具│/stderr 工具│，流内保序、不假定跨流总顺序。"""

    def tool(context: ExecutionContext) -> None:
        result = context.run_process(
            ToolCommand(
                "测试工具",
                (
                    sys.executable,
                    "-u",
                    "-c",
                    "import sys; print('甲'); print('乙'); print('错误甲',file=sys.stderr); print('错误乙',file=sys.stderr)",
                ),
                tmp_path,
                3.0,
            )
        )
        assert result == 0

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, tool) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert (
            record is not None
            and record.summary is not None
            and record.summary.outcome == "succeeded"
        )
        assert record.tool_exit_code == 0 and record.log_path is not None
        lines = (dependencies.paths.root / record.log_path).read_text().splitlines()
        assert [
            line.split("stdout 测试工具│", 1)[1] for line in lines if "stdout 测试工具│" in line
        ] == ["甲", "乙"]
        assert [
            line.split("stderr 测试工具│", 1)[1] for line in lines if "stderr 测试工具│" in line
        ] == ["错误甲", "错误乙"]
        assert not any(thread.is_alive() for thread in signals.monitor.threads)


def test_large_output(tmp_path: Path) -> None:
    """规范2.7/6.9：超长无换行/非法UTF8分段可追溯，完整内容写文件，stderr尾摘要有字节和行数上限。"""
    code = "import os; os.write(1, b'x'*50000+b'\\xff\\n'); os.write(2, b'y'*50000+b'\\n'); raise SystemExit(7)"

    def tool(context: ExecutionContext) -> None:
        context.run_process(ToolCommand("长输出", (sys.executable, "-c", code), tmp_path, 3.0))

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, tool) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert (
            record is not None and record.summary is not None and record.summary.outcome == "failed"
        )
        assert record.tool_exit_code == 7 and record.log_path is not None
        lines = (dependencies.paths.root / record.log_path).read_text().splitlines()
        chunks = [
            line.split("stdout 长输出│", 1)[1].removeprefix("[续行]")
            for line in lines
            if "stdout 长输出│" in line
        ]
        assert "".join(chunks) == "x" * 50000 + "\\xff"
        stderr = [
            line.split("stderr 长输出│", 1)[1].removeprefix("[续行]")
            for line in lines
            if "stderr 长输出│" in line
        ]
        assert "".join(stderr) == "y" * 50000
        assert any("[续行]" in line for line in lines)
        diagnostic = record.diagnostics[0].samples[0]
        tail = next(item.value for item in diagnostic.objects if item.key == "stderr_tail")
        assert len(tail.encode()) <= 32768 and "截断" in tail
        assert not any(thread.is_alive() for thread in signals.monitor.threads)


def test_bounded_tail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """尾读契约：超过64KiB大日志只seek末尾有限字节、返回最后50完整行，半字符/半行标截断。"""
    with job_database(tmp_path) as (_, paths):
        target = paths.logs / "large.log"
        target.write_text(
            "字" * 30000 + "\n" + "".join(f"完整行{i}\n" for i in range(80)) + "未写完"
        )
        original = Path.open
        reads: list[int] = []

        class BoundedReader:
            def __init__(self, stream: IO[bytes]) -> None:
                self.stream = stream

            def __enter__(self) -> "BoundedReader":
                return self

            def __exit__(self, *_: object) -> None:
                self.stream.close()

            def seek(self, offset: int, whence: int = 0) -> int:
                return self.stream.seek(offset, whence)

            def tell(self) -> int:
                return self.stream.tell()

            def read(self, size: int = -1) -> bytes:
                assert 0 <= size <= 65536
                reads.append(size)
                return self.stream.read(size)

        def checked(path: Path, *args: object, **kwargs: object) -> object:
            assert path == target and args == ("rb",) and not kwargs
            return BoundedReader(cast(IO[bytes], original(path, "rb")))

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", checked)
            result = read_log_tail(paths, "logs/large.log")
        assert result.status == "available" and result.truncated
        assert result.lines == tuple(f"完整行{i}" for i in range(30, 80))
        assert sum(reads) <= 65536
        target.write_bytes(b"first\nsecond\n")
        tail = read_log_tail(paths, "logs/large.log")
        assert tail.lines == ("first", "second") and not tail.truncated
        target.write_bytes(b"partial")
        assert read_log_tail(paths, "logs/large.log").lines == ()


def test_missing_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """尾读契约：路径None为not_started，已删除文件cleared且HTTP200，权限错误不是cleared。"""
    from typing import Any

    from jobs_api_support import job_api_case

    from rdp.infra.config import PlatformConfig
    from rdp.infra.state import state_paths

    with job_api_case(tmp_path) as fixture:
        fixture.login()
        submitted = fixture.client.post(
            "/api/jobs/example", json={"steps": 3, "interval_ms": 0}
        ).json()
        identifier = submitted["job_id"]
        path = f"/api/jobs/{identifier}/log"
        assert fixture.client.get(path).json()["tail"]["status"] == "not_started"
        paths = state_paths(PlatformConfig(state_dir=tmp_path), ("示例：数数",))
        with session_scope(fixture.engine) as session:
            record = claim_job(
                session, int(identifier), now=fixture.clock.value, paths=paths, gpu_index=None
            )
        assert record.log_path is not None
        target = tmp_path / record.log_path
        target.write_text("旧日志\n")
        assert fixture.client.get(path).json()["tail"]["lines"] == ["旧日志"]
        target.unlink()
        response = fixture.client.get(path)
        assert response.status_code == 200 and response.json()["tail"]["status"] == "cleared"
        target.touch()
        original = Path.open

        def denied(path: Path, mode: str = "r", **kwargs: Any) -> IO[Any]:
            if path == target:
                raise PermissionError("测试日志权限失败")
            return original(path, mode, **kwargs)

        monkeypatch.setattr(Path, "open", denied)
        response = fixture.client.get(path)
        assert response.status_code == 502 and "cleared" not in response.text


def test_path_escape(tmp_path: Path) -> None:
    """尾读契约：绝对路径、..、越界软链接、非普通文件归DefectError，不读取状态logs以外路径。"""
    with job_database(tmp_path) as (engine, paths):
        outside = tmp_path / "outside-secret"
        outside.write_text("不可读取")
        (paths.logs / "link").symlink_to(outside)
        (paths.logs / "directory").mkdir()
        for relative in (
            str(outside),
            "logs/../outside-secret",
            "outside-secret",
            "logs/link",
            "logs/directory",
            "logs",
        ):
            with pytest.raises(DefectError):
                read_log_tail(paths, relative)
        with session_scope(engine) as session:
            session.add(job_row())
        with session_scope(engine, read_only=True) as session:
            record = find_job(session, 71)
        for relative in ("logs/link", "logs/示例：数数/wrong.log", "../outside-secret"):
            with pytest.raises(DefectError):
                open_job_log(paths, replace(record, log_path=relative))


def test_recovery_log_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """验收3：每种恢复先flush中断段，再状态改变/清零/执行；中断段失败不执行该条，只尝试隔离终态，失败ERROR跳过后仍处理其他作业。"""
    from jobs_loop_support import running_loop, wait_for

    from rdp.jobs import policy

    for mode in ("resume", "restart", "interrupt", "cancel"):
        _recovery_segment_before_commit(tmp_path / mode, mode)
    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.005)

    def fail_segment(*_args: object, **_kwargs: object) -> None:
        raise OSError("测试中断段写失败")

    with execution_case(
        tmp_path / "failure", {"steps": 3, "interval_ms": 0}, mode=RecoveryMode.RESUME
    ) as (_, dependencies, _):
        with session_scope(dependencies.engine) as session:
            session.add(job_row(JobState.QUEUED, job_id=72))
        monkeypatch.setattr(JobLog, "write_interruption", fail_segment)

        def completed() -> bool:
            with session_scope(dependencies.engine, read_only=True) as session:
                return find_job(session, 72).state is JobState.COMPLETED

        with running_loop(dependencies) as (_, _, results):
            wait_for(completed)
        assert (
            results[0].code == 0 and saved_record(dependencies.engine).state is JobState.INTERRUPTED
        )
        assert any("中断段可能缺失" in entry.getMessage() for entry in caplog.records)


def test_recovery_log_deleted(tmp_path: Path) -> None:
    """恢复日志：原文件已清除时原路径重建并明确历史缺失，续跑/重跑不换文件名。"""
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, mode=RecoveryMode.RESUME) as (
        work,
        dependencies,
        _,
    ):
        log, _ = open_job_log(dependencies.paths, work.record)
        try:
            log.write_header(work.record, EMPTY_METADATA)
        finally:
            log.close()
        assert work.record.log_path is not None
        target = dependencies.paths.root / work.record.log_path
        target.unlink()
        recovered = recover_job(71, dependencies)
        assert recovered is not None and recovered.record.log_path == work.record.log_path
        content = target.read_text()
        assert "登记的日志文件不存在" in content
        assert content.index("作业开头") < content.index("中断")


def test_summary_io_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """日志故障：数据库终态提交后写结尾失败，保留终态且边界ERROR，不回滚或伪造另一结局。"""

    def fail_summary(self: JobLog, summary: JobSummary, *, now: object) -> None:
        raise OSError("测试磁盘写失败")

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}) as (work, dependencies, signals):
        monkeypatch.setattr(JobLog, "write_summary", fail_summary)
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.state is JobState.COMPLETED
        assert record == saved_record(dependencies.engine) and record.summary is not None
        assert record.summary.outcome == "succeeded"
        assert any("日志结尾写入失败" in entry.getMessage() for entry in caplog.records)
        assert record.log_path is not None
        assert "summary=" not in (dependencies.paths.root / record.log_path).read_text()


def test_close_resources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """日志资源：打开/写/flush/close故障保留主异常，finally关闭描述符，不截断旧文件。"""
    original = Path.open

    class FaultyFile:
        def __init__(self, path: Path) -> None:
            self.stream = original(path, "a", encoding="utf-8")

        def write(self, value: str) -> int:
            return self.stream.write(value)

        def flush(self) -> None:
            raise OSError("flush-first")

        def close(self) -> None:
            self.stream.close()
            raise OSError("close-second")

    target = tmp_path / "fault.log"
    target.write_text("旧内容\n")
    stream = FaultyFile(target)

    def open_faulty(*_args: object, **_kwargs: object) -> FaultyFile:
        return stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_faulty)
        log = JobLog(target)
    try:
        with pytest.raises(ExternalError) as caught:
            log.close()
        assert caught.value.__cause__ is not None and caught.value.__cause__.args == (
            "flush-first",
        )
        assert stream.stream.closed and target.read_text() == "旧内容\n"
        log.close()
    finally:
        stream.stream.close()


def test_claim_crash_before_header(tmp_path: Path) -> None:
    """第4条：领取事务提交后、写头前真实崩溃，记录已有非空log_path；恢复新建该文件先写开头再写中断段，开始时间不变。"""
    import signal
    import subprocess

    from job_process_support import (
        PROCESS_EXIT_TIMEOUT_S,
        PROCESS_READY_TIMEOUT_S,
        prepare_process_case,
    )

    case = prepare_process_case(tmp_path, "claim_gap")
    runner = Path(__file__).with_name("job_worker_process.py")
    first: subprocess.Popen[bytes] | None = None
    second: subprocess.Popen[bytes] | None = None
    try:
        first = subprocess.Popen(  # noqa: S603  # 理由：仅固定本地夹具与当前解释器，无shell。
            [sys.executable, str(runner), str(tmp_path), "claim_gap"], start_new_session=True
        )
        before = case.wait_claimed_before_log(PROCESS_READY_TIMEOUT_S)
        assert before.log_path is not None and not (tmp_path / before.log_path).exists()
        first.kill()
        assert first.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == -signal.SIGKILL
        second = subprocess.Popen(  # noqa: S603  # 理由：独立新进程验证真实崩溃后的日志恢复。
            [sys.executable, str(runner), str(tmp_path), "interrupt"], start_new_session=True
        )
        after = case.wait_terminal(PROCESS_READY_TIMEOUT_S)
        assert after.started_at == before.started_at and after.log_path == before.log_path
        content = (tmp_path / before.log_path).read_text()
        assert f"job_id={before.job_id}" in content and "测试作业" in content
        assert (
            content.index("作业开头") < content.index(" interruption=") < content.index(" summary=")
        )
        assert case.interruption()[0] is None
        case.stop()
        assert second.wait(timeout=PROCESS_EXIT_TIMEOUT_S) == 0
    finally:
        try:
            for process in (second, first):
                if process is not None:
                    if process.poll() is None:
                        process.kill()
                    process.wait(timeout=PROCESS_EXIT_TIMEOUT_S)
        finally:
            case.cleanup_orphans()


def test_claim_atomic_path(tmp_path: Path) -> None:
    """第4条：queued→running、started_at、log_path同事务；提交失败三者回滚，不能出现running且路径为空。"""
    with job_database(tmp_path) as (engine, paths):
        with session_scope(engine) as session:
            session.add(job_row(JobState.QUEUED))
        with pytest.raises(RuntimeError, match="提交失败"), session_scope(engine) as session:
            claimed = claim_job(session, 71, now=NOW, paths=paths, gpu_index=None)
            assert (
                claimed.state is JobState.RUNNING and claimed.started_at == NOW and claimed.log_path
            )
            raise RuntimeError("提交失败")
        record = saved_record(engine)
        assert record.state is JobState.QUEUED and record.started_at is record.log_path is None


def test_tail_local_missing_and_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """文件边界区分未开始、已清除和权限故障；空文件正常可读，错误诊断含受限日志路径。"""
    with job_database(tmp_path) as (_, paths):
        assert read_log_tail(paths, None).status == "not_started"
        missing = read_log_tail(paths, "logs/missing.log")
        assert missing.status == "cleared" and missing.lines == ()
        target = paths.logs / "empty.log"
        target.touch()
        assert read_log_tail(paths, "logs/empty.log").status == "available"

        def denied(*_: object, **__: object) -> None:
            raise PermissionError("私密底层消息")

        with monkeypatch.context() as patch:
            patch.setattr(Path, "open", denied)
            with pytest.raises(ExternalError) as caught:
                read_log_tail(paths, "logs/empty.log")
            assert caught.value.diagnostics[0].objects[0].value == str(target)
            assert "私密" not in str(caught.value)


def test_diagnostic_and_interruption_segments(tmp_path: Path) -> None:
    """日志原文保留诊断五段和每次中断的全部阶段/计数/方式/原因；拒绝空原因，不制造最后进度。"""
    target = tmp_path / "segments.log"
    log = JobLog(target)
    diagnostic = Diagnostic(
        level=DiagnosticLevel.WARNING,
        category=DiagnosticCategory.INPUT,
        stage="处理",
        source="平台",
        objects=(DiagnosticObject(key="job_id", value="71"),),
        rule="样例规则",
        actual="第2条有警告",
        expected="无警告",
        consequence="继续处理剩余条目",
        next_step="查看第2条",
    )
    try:
        log.write_diagnostic(diagnostic, now=NOW)
        progress = JobProgress.model_validate(PROGRESS)
        log.write_interruption(progress, RecoveryMode.RESUME, now=NOW, reason="按当前登记续跑")
        log.write_interruption(None, RecoveryMode.INTERRUPT, now=NOW, reason="恢复次数已达3次")
        content = target.read_text()
        for line in render_diagnostic(diagnostic).splitlines():
            assert line in content
        lines = [
            line.split("interruption=", 1)[1]
            for line in content.splitlines()
            if "interruption=" in line
        ]
        data = [json.loads(line) for line in lines]
        assert data[0] == {"progress": PROGRESS, "mode": "resume", "reason": "按当前登记续跑"}
        assert data[1] == {"progress": None, "mode": "interrupt", "reason": "恢复次数已达3次"}
        assert "尚未上报" in content and "中断" in content
        with pytest.raises(DefectError):
            log.write_interruption(progress, RecoveryMode.RESUME, now=NOW, reason="")
    finally:
        log.close()


def test_header_rejects_byte_oversize_and_nonobject(tmp_path: Path) -> None:
    """开头配置按UTF8字节限制16KiB，参数必须为JSON对象；错误输入不追加伪开头。"""
    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}) as (work, dependencies, _):
        log, _ = open_job_log(dependencies.paths, work.record)
        try:
            with pytest.raises(DefectError):
                log.write_header(work.record, JobLogMetadata("字" * 6000, None, None))
            with pytest.raises(DefectError):
                log.write_header(
                    replace(work.record, parameters=cast(dict[str, object], None)), EMPTY_METADATA
                )
            assert work.record.log_path is not None
            assert not (dependencies.paths.root / work.record.log_path).read_text()
        finally:
            log.close()


def test_stderr_tail_byte_boundary_marks_truncation(tmp_path: Path) -> None:
    """stderr分段间的换行也计入32KiB上限；恰好32KiB原文拼接后溢出必须明确标记截断。"""

    def tool(context: ExecutionContext) -> None:
        context.run_process(
            ToolCommand(
                "边界工具",
                (
                    sys.executable,
                    "-c",
                    r"import os; os.write(2,b'a'*32768+b'\n'); raise SystemExit(7)",
                ),
                tmp_path,
                3,
            )
        )

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, tool) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.diagnostics and record.tool_exit_code == 7
        tail = next(
            item.value
            for item in record.diagnostics[0].samples[0].objects
            if item.key == "stderr_tail"
        )
        assert len(tail.encode()) <= 32768 and "截断" in tail


def test_large_summary_preserves_all_artifacts(tmp_path: Path) -> None:
    """合法的100个长产物位置仍需完整写结尾；平台过程消息64KiB上限不能截断合法的冻结摘要。"""
    locations = tuple(f"{index:03d}/" + "x" * 4090 for index in range(100))

    def execute(context: ExecutionContext) -> None:
        for location in locations:
            context.reporter.artifact(location)

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, execute) as (
        work,
        dependencies,
        signals,
    ):
        record = execute_job(work, dependencies, signals)
        assert record is not None and record.log_path is not None and record.summary is not None
        data = (dependencies.paths.root / record.log_path).read_text()
        summary = json.loads(data.split("summary=", 1)[1])
        assert tuple(summary["artifacts"]) == record.summary.artifacts == locations


def _recovery_segment_before_commit(root: Path, mode: str) -> None:
    """在数据库写边界观察已flush的日志，逐模式核对旧进度与处理方式。"""
    from sqlalchemy import Connection, event

    from rdp.jobs.records import StateChange, save_progress, transition_job
    from rdp.jobs.types import ExecutionSnapshot

    recovery = RecoveryMode.RESUME if mode == "cancel" else RecoveryMode(mode)
    with execution_case(root, {"steps": 3, "interval_ms": 0}, mode=recovery) as (
        work,
        dependencies,
        _,
    ):
        with session_scope(dependencies.engine) as session:
            save_progress(
                session,
                71,
                ExecutionSnapshot(JobProgress.model_validate(PROGRESS), (), (), None, 2),
                now=NOW,
            )
            if mode == "cancel":
                transition_job(session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW))
        assert work.record.log_path is not None
        target = dependencies.paths.root / work.record.log_path
        observed: list[str] = []

        def before_write(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: bool,
        ) -> None:
            if statement.startswith("UPDATE jobs"):
                content = target.read_text()
                assert " interruption=" in content
                interruption = json.loads(content.split("interruption=", 1)[1].splitlines()[0])
                assert interruption["progress"] == PROGRESS and interruption["mode"] == mode
                observed.append(statement)

        event.listen(dependencies.engine, "before_cursor_execute", before_write)
        try:
            recover_job(71, dependencies)
            assert observed
        finally:
            event.remove(dependencies.engine, "before_cursor_execute", before_write)


def test_recovery_cancel_committed_before_resume(tmp_path: Path) -> None:
    """评审4：恢复已读到running后另一事务提交取消，必须另写取消中断段，再以已取消收尾。"""
    from sqlalchemy import Connection, event

    from rdp.jobs.records import StateChange, save_progress, transition_job
    from rdp.jobs.types import ExecutionSnapshot

    with execution_case(tmp_path, {"steps": 3, "interval_ms": 0}, mode=RecoveryMode.RESUME) as (
        work,
        dependencies,
        _,
    ):
        previous = JobProgress.model_validate(PROGRESS)
        with session_scope(dependencies.engine) as session:
            save_progress(session, 71, ExecutionSnapshot(previous, (), (), None, 2), now=NOW)
        assert work.record.log_path is not None
        target = dependencies.paths.root / work.record.log_path
        cancelled = False

        def before_write(
            _connection: Connection,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _many: bool,
        ) -> None:
            nonlocal cancelled
            if statement == "BEGIN IMMEDIATE" and not cancelled:
                # 恢复已写完首次中断段，且尚未取得提交写锁；用另一连接真正提交取消。
                assert '"mode": "resume"' in target.read_text()
                cancelled = True
                with session_scope(dependencies.engine) as session:
                    transition_job(
                        session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                    )

        event.listen(dependencies.engine, "before_cursor_execute", before_write)
        try:
            assert recover_job(71, dependencies) is None
        finally:
            event.remove(dependencies.engine, "before_cursor_execute", before_write)
        record = saved_record(dependencies.engine)
        assert cancelled and record.state is JobState.CANCELLED
        assert (
            record.progress == previous
            and record.summary is not None
            and record.summary.outcome is None
        )
        lines = target.read_text().splitlines()
        segments = [
            json.loads(line.split("interruption=", 1)[1])
            for line in lines
            if "interruption=" in line
        ]
        assert [item["mode"] for item in segments] == ["resume", "cancel"]
        assert segments[1]["reason"] == "恢复期间收到取消请求"
        assert segments[1]["progress"] == PROGRESS
        assert next(
            index for index, line in enumerate(lines) if "恢复期间收到取消请求" in line
        ) < next(index for index, line in enumerate(lines) if "summary=" in line)
