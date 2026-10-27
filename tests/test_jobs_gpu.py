"""GPU行为测试；唯一外部工具是测试生成的假nvidia-smi，不探测真实硬件。"""

import json
import os
import signal
import sys
from collections.abc import Generator
from contextlib import suppress
from dataclasses import replace
from pathlib import Path

import pytest
from jobs_gpu_support import gpu_case, signals_fixture
from jobs_storage_support import NOW

from rdp.infra.db.connection import session_scope
from rdp.jobs.execution import execute_job, recover_job
from rdp.jobs.navigation import NavigationWriter
from rdp.jobs.records import StateChange, transition_job
from rdp.jobs.resources import ResourcePool, reset_resources_on_startup
from rdp.jobs.scheduling import Scheduler
from rdp.jobs.types import JobState

# 假脚本用相邻的 mode 文件控制场景，不接受外部命令；即使未配置 mode 也只报告虚构的两张卡。
# CUDA 环境由框架注入，脚本把实际继承值写到 stderr，测试独立断言并发隔离而非假装查询了真实 GPU。
FAKE_NVIDIA_SMI_SCRIPT = r"""#!/usr/bin/env python3
import json
import os
import pathlib
import sys
import time

record_path = pathlib.Path(__file__).with_name(f"call-{os.getpid()}.json")
writing = record_path.with_suffix(".writing")
writing.write_text(json.dumps({"argv":sys.argv[1:], "pid":os.getpid(), "CUDA_VISIBLE_DEVICES":os.environ.get("CUDA_VISIBLE_DEVICES"), "CUDA_DEVICE_ORDER":os.environ.get("CUDA_DEVICE_ORDER")}))
writing.replace(record_path)
mode_path = pathlib.Path(__file__).with_name("mode")
mode = mode_path.read_text().strip() if mode_path.exists() else "two"
if mode == "timeout":
    time.sleep(30)
if mode == "failure":
    sys.stderr.write("模拟驱动不可用\n")
    sys.exit(9)
if mode == "blank_stderr":
    sys.stderr.write(" \n\t")
    sys.exit(7)
if mode == "large_stderr":
    for index in range(10000):
        sys.stderr.write(f"模拟长输出 {index}\n")
    sys.exit(8)
if mode == "malformed":
    sys.stdout.write("坏卡号\n")
    sys.exit(0)
if any(arg.startswith("--query-gpu") for arg in sys.argv):
    sys.stdout.write("0\n" if mode == "missing" else "0\n1\n")
else:
    sys.stdout.write("模拟 nvidia-smi 输出\n")
    sys.stderr.write("CUDA_VISIBLE_DEVICES=" + os.environ.get("CUDA_VISIBLE_DEVICES", "缺失") + "\n")
    sys.stderr.write("CUDA_DEVICE_ORDER=" + os.environ.get("CUDA_DEVICE_ORDER", "缺失") + "\n")
"""


@pytest.fixture
def fake_nvidia_smi(tmp_path: Path) -> Generator[Path]:
    """GPU 契约夹具：仅在临时目录生成可执行替身，进程由被测框架及测试 finally 回收。"""
    path = tmp_path / "nvidia-smi"
    path.write_text(
        "#!" + sys.executable + "\n" + FAKE_NVIDIA_SMI_SCRIPT.split("\n", 1)[1], encoding="utf-8"
    )
    path.chmod(0o700)
    try:
        yield path
    finally:
        # 被测代码失败时仍按记录的独立进程组清理，不接触其他命令。
        _kill_fake_groups(tmp_path)


def _kill_fake_groups(root: Path) -> None:
    """根据临时脚本写出的PID回收独立组，直接子进程仍由生产入口wait收割。"""
    for call in root.glob("call-*.json"):
        pid = json.loads(call.read_text(encoding="utf-8"))["pid"]
        with suppress(ProcessLookupError):
            os.killpg(pid, signal.SIGKILL)


def test_two_cards_three_jobs(fake_nvidia_smi: Path) -> None:
    """验收2：两卡三作业前两项各领不同卡、先领最小空卡；第三项queued且等待GPU，归还后才开始。"""
    from jobs_gpu_support import gpu_case, signals_fixture

    from rdp.jobs.execution import execute_job
    from rdp.jobs.types import JobState, WaitReason

    with gpu_case(fake_nvidia_smi.parent / "state", fake_nvidia_smi) as case:
        for number in (71, 72, 73):
            case.add(number)
        first, second = case.scheduler.claim_next(), case.scheduler.claim_next()
        assert first is not None and second is not None
        assert (
            first.record.job_id,
            first.record.gpu_index,
            second.record.job_id,
            second.record.gpu_index,
        ) == (71, 0, 72, 1)
        assert case.scheduler.claim_next() is None
        waiting = case.get(73)
        assert waiting.state is JobState.QUEUED and waiting.wait_reason is WaitReason.GPU
        assert len(case.resources.pool.claims()) == 2
        result = execute_job(first, case.dependencies, signals_fixture())
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
        )
        third = case.scheduler.claim_next()
        assert third is not None and third.record.job_id == 73 and third.record.gpu_index == 0
        assert third.record.wait_reason is None
        for work in (second, third):
            result = execute_job(work, case.dependencies, signals_fixture())
            assert (
                result is not None
                and result.summary is not None
                and result.summary.outcome == "succeeded"
            )
        assert case.resources.pool.claims() == ()
        assert [case.get(number).gpu_index for number in (71, 72, 73)] == [0, 1, 0]


@pytest.mark.parametrize("ending", ["completed", "failed", "cancelled", "stopped", "interrupted"])
def test_release_all_endings(fake_nvidia_smi: Path, ending: str) -> None:
    """验收2：完成/失败/取消/停止/崩溃后恢复的每种路径不漏名额，后续作业可用卡，终态记录保留卡号。"""
    with gpu_case(fake_nvidia_smi.parent / "state", fake_nvidia_smi, gpus=(0,)) as case:
        case.add(71)
        work = case.scheduler.claim_next()
        assert work is not None and work.record.gpu_index == 0
        signals = signals_fixture()
        resources, scheduler = case.resources, case.scheduler
        if ending == "interrupted":
            resources = replace(
                resources,
                pool=ResourcePool(resources.configuration.catalog.settings, available_gpus=(0,)),
                navigation=NavigationWriter(),
            )
            dependencies = replace(case.dependencies, resources=resources)
            with session_scope(dependencies.engine) as session:
                reset_resources_on_startup(session)
            assert recover_job(71, dependencies) is None
            scheduler = Scheduler(dependencies, resources, recovered=())
            assert case.get(71).state is JobState.INTERRUPTED and case.get(71).gpu_index is None
        else:
            if ending == "failed":
                fake_nvidia_smi.with_name("mode").write_text("failure", encoding="utf-8")
            if ending == "cancelled":
                with session_scope(case.dependencies.engine) as session:
                    transition_job(
                        session, 71, StateChange(JobState.RUNNING, JobState.CANCELLING, NOW)
                    )
                signals.cancelled.set()
            if ending == "stopped":
                signals.stopping.set()
            result = execute_job(work, case.dependencies, signals)
            saved = case.get(71)
            assert saved.gpu_index == 0
            if ending == "stopped":
                assert result is None and saved.state is JobState.RUNNING
            else:
                assert result is not None and result.summary is not None
                assert result.state is (
                    JobState.CANCELLED if ending == "cancelled" else JobState.COMPLETED
                )
                if ending in {"failed", "completed"}:
                    assert result.summary.outcome == (
                        "failed" if ending == "failed" else "succeeded"
                    )
        assert resources.pool.claims() == ()
        case.add(72)
        following = scheduler.claim_next()
        assert (
            following is not None
            and following.record.gpu_index == 0
            and following.claim is not None
        )
        resources.pool.release(following.claim)


@pytest.mark.parametrize("mode", ["missing", "failure", "timeout", "malformed", "blank_stderr"])
def test_probe_failures(fake_nvidia_smi: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收3：缺卡/非零/超时/坏输出/空白stderr均ExternalError，诊断有卡号、命令、stderr尾和后果，作业失败且归还卡。"""
    from jobs_gpu_support import gpu_case, signals_fixture

    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs import policy
    from rdp.jobs.execution import execute_job
    from rdp.jobs.gpu import verify_gpu

    fake_nvidia_smi.with_name("mode").write_text(mode, encoding="utf-8")
    monkeypatch.setattr(policy, "GPU_PROBE_TIMEOUT_S", 0.15)
    with pytest.raises(ExternalError) as caught:
        verify_gpu(1, fake_nvidia_smi, log=None)
    diagnostic = caught.value.diagnostics[0]
    objects = {item.key: item.value for item in diagnostic.objects}
    assert objects["gpu_index"] == "1" and str(fake_nvidia_smi) in objects["command"]
    assert objects["stderr_tail"].strip() and diagnostic.consequence and diagnostic.next_step
    expected = {
        "missing": "看不到",
        "failure": "非零",
        "timeout": "超时",
        "malformed": "格式损坏",
        "blank_stderr": "非零",
    }
    assert expected[mode] in diagnostic.actual
    if mode == "failure":
        assert "模拟驱动不可用" in objects["stderr_tail"] and objects["returncode"] == "9"
    with gpu_case(
        fake_nvidia_smi.parent / "state",
        fake_nvidia_smi,
        gpus=(1,),
        execute=lambda _context: pytest.fail("核对失败不得执行类型"),
    ) as case:
        case.add(71)
        work = case.scheduler.claim_next()
        assert work is not None
        result = execute_job(work, case.dependencies, signals_fixture())
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        assert result.diagnostics[0].samples[0].category == "external"
        assert result.gpu_index == 1 and case.resources.pool.claims() == ()
    for call in fake_nvidia_smi.parent.glob("call-*.json"):
        pid = json.loads(call.read_text(encoding="utf-8"))["pid"]
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


def test_startup_missing_card(fake_nvidia_smi: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收3：启动核对每张配置卡，失败记worker.log一次ERROR并移出本实例池，其他好卡可分配，CPU作业仍可开始。"""
    from jobs_gpu_support import gpu_case, running_gpu_worker
    from jobs_loop_support import wait_for
    from sqlalchemy import select

    from rdp.infra.db.connection import session_scope
    from rdp.jobs import policy
    from rdp.jobs.models import WorkerHeartbeatRow
    from rdp.jobs.scheduling_models import WorkerGpuCheckRow
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    fake_nvidia_smi.with_name("mode").write_text("missing", encoding="utf-8")
    with gpu_case(fake_nvidia_smi.parent / "state", fake_nvidia_smi) as case:
        case.add(71)
        case.add(72, gpu=False)
        with running_gpu_worker(case):
            wait_for(
                lambda: all(case.get(number).state is JobState.COMPLETED for number in (71, 72))
            )
            assert case.get(71).gpu_index == 0 and case.get(72).gpu_index is None
            summaries = [case.get(number).summary for number in (71, 72)]
            assert all(
                summary is not None and summary.outcome == "succeeded" for summary in summaries
            )
            with session_scope(case.dependencies.engine, read_only=True) as session:
                rows = session.scalars(
                    select(WorkerGpuCheckRow).order_by(WorkerGpuCheckRow.gpu_index)
                ).all()
                heartbeat = session.get(WorkerHeartbeatRow, 1)
                assert heartbeat is not None and len(rows) == 2
                assert [(row.gpu_index, row.available) for row in rows] == [(0, True), (1, False)]
                assert all(row.instance_id == heartbeat.instance_id for row in rows)
        text = (case.dependencies.paths.logs / "worker.log").read_text(encoding="utf-8")
        assert text.count("ERROR") == 1 and "gpu_index=1" in text and "移出" in text


def test_recheck_after_claim(fake_nvidia_smi: Path) -> None:
    """验收3：启动时存在而领取后消失的卡也必须重新核对，类型execute不被调用，不回退CPU。"""
    from jobs_gpu_support import gpu_case, signals_fixture

    from rdp.jobs.execution import execute_job
    from rdp.jobs.gpu import verify_gpu

    verify_gpu(1, fake_nvidia_smi, log=None)
    calls: list[int] = []
    with gpu_case(
        fake_nvidia_smi.parent / "state",
        fake_nvidia_smi,
        gpus=(1,),
        execute=lambda context: calls.append(context.job_id),
    ) as case:
        case.add(71)
        work = case.scheduler.claim_next()
        assert work is not None and work.record.gpu_index == 1
        fake_nvidia_smi.with_name("mode").write_text("missing", encoding="utf-8")
        result = execute_job(work, case.dependencies, signals_fixture())
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        assert result.diagnostics[0].samples[0].category == "external" and calls == []
        assert case.resources.pool.claims() == ()
        assert len(tuple(fake_nvidia_smi.parent.glob("call-*.json"))) == 2
        # 执行前故障只归还本次凭据，不改变本实例已通过启动核对的池成员。
        case.add(72)
        following = case.scheduler.claim_next()
        assert following is not None and following.record.gpu_index == 1


def test_disabled_gpu(fake_nvidia_smi: Path) -> None:
    """K1：空GPU配置的需卡作业领取后外部失败，诊断明确没有配置可用卡，不无限queued。"""
    from jobs_gpu_support import gpu_case, signals_fixture

    from rdp.jobs.execution import execute_job

    with gpu_case(
        fake_nvidia_smi.parent / "state",
        fake_nvidia_smi,
        gpus=(),
        execute=lambda _context: pytest.fail("无卡不得执行类型"),
    ) as case:
        case.add(71)
        work = case.scheduler.claim_next()
        assert work is not None and work.record.state.value == "running"
        result = execute_job(work, case.dependencies, signals_fixture())
        assert (
            result is not None and result.summary is not None and result.summary.outcome == "failed"
        )
        diagnostic = result.diagnostics[0].samples[0]
        assert diagnostic.category == "external" and "没有可用的卡" in diagnostic.actual
        assert result.gpu_index is None and result.wait_reason is None
        assert case.resources.pool.claims() == ()
    assert not tuple(fake_nvidia_smi.parent.glob("call-*.json"))


def test_child_environment(fake_nvidia_smi: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """验收2：并发子进程分别继承自己的CUDA_VISIBLE_DEVICES及PCI_BUS_ID，不修改父环境、不串卡。"""
    from dataclasses import replace
    from threading import Thread

    from jobs_execution_support import execution_case

    from rdp.jobs.execution import ExecutionContext, execute_job
    from rdp.jobs.processes import ToolCommand

    monkeypatch.setenv("CUDA_VISIBLE_DEVICES", "父进程原值")
    monkeypatch.setenv("CUDA_DEVICE_ORDER", "FASTEST_FIRST")
    before = {key: os.environ.get(key) for key in ("CUDA_VISIBLE_DEVICES", "CUDA_DEVICE_ORDER")}
    results: list[str] = []
    errors: list[BaseException] = []

    def run(index: int) -> None:
        def execute(context: ExecutionContext) -> None:
            command = ToolCommand(
                "nvidia-smi", (str(fake_nvidia_smi), "-i", str(index)), fake_nvidia_smi.parent, 1
            )
            replace(context, gpu_index=index).run_process(command)

        try:
            with execution_case(
                fake_nvidia_smi.parent / str(index), {"steps": 1, "interval_ms": 0}, execute
            ) as (work, deps, signals):
                result = execute_job(work, deps, signals)
                assert (
                    result is not None
                    and result.summary is not None
                    and result.summary.outcome == "succeeded"
                )
                assert result.log_path is not None
                results.append((deps.paths.root / result.log_path).read_text(encoding="utf-8"))
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=run, args=(index,), daemon=True) for index in (0, 1)]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=3)
        assert not any(thread.is_alive() for thread in threads)
    finally:
        if any(thread.is_alive() for thread in threads):
            _kill_fake_groups(fake_nvidia_smi.parent)
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=3)
                assert not thread.is_alive()
    assert errors == [] and len(results) == 2
    calls = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in fake_nvidia_smi.parent.glob("call-*.json")
    ]
    assert {(item["CUDA_VISIBLE_DEVICES"], item["CUDA_DEVICE_ORDER"]) for item in calls} == {
        ("0", "PCI_BUS_ID"),
        ("1", "PCI_BUS_ID"),
    }
    assert {key: os.environ.get(key) for key in before} == before
    assert all(
        "CUDA_VISIBLE_DEVICES=" in log and "CUDA_DEVICE_ORDER=PCI_BUS_ID" in log for log in results
    )


def test_header_and_card_line(fake_nvidia_smi: Path) -> None:
    """契约：作业开头后写卡号，进程启动前写最终CUDA两项实际值，nvidia-smi用-i，stdout/stderr带前缀经JobLog完整写入。"""
    from jobs_gpu_support import gpu_case, signals_fixture

    from rdp.jobs.execution import execute_job

    with gpu_case(fake_nvidia_smi.parent / "state", fake_nvidia_smi, gpus=(1,)) as case:
        case.add(71)
        work = case.scheduler.claim_next()
        assert work is not None
        result = execute_job(work, case.dependencies, signals_fixture())
        assert (
            result is not None
            and result.summary is not None
            and result.summary.outcome == "succeeded"
        )
        assert result.summary.total_items == 1 and result.log_path is not None
        text = (case.dependencies.paths.root / result.log_path).read_text(encoding="utf-8")
        assert text.index("作业") < text.index("领到GPU卡号：1") < text.index("stdout nvidia-smi│1")
        assert "CUDA_VISIBLE_DEVICES=1 CUDA_DEVICE_ORDER=PCI_BUS_ID" in text
        assert "stdout nvidia-smi│模拟 nvidia-smi 输出" in text
        assert "stderr nvidia-smi│CUDA_VISIBLE_DEVICES=1" in text
        assert text.index("CUDA_VISIBLE_DEVICES=1 CUDA_DEVICE_ORDER=PCI_BUS_ID") < text.index(
            "stdout nvidia-smi│模拟"
        )
    calls = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in fake_nvidia_smi.parent.glob("call-*.json")
    ]
    executed = [call for call in calls if call["argv"] == ["-i", "1"]]
    assert len(calls) == 2 and len(executed) == 1
    assert (
        executed[0]["CUDA_VISIBLE_DEVICES"] == "1"
        and executed[0]["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    )


def test_probe_large_output(fake_nvidia_smi: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：假工具大量输出完整入日志，内存及诊断stderr尾有界且标记截断，超时回收不留子进程。"""
    from rdp.infra.diagnostics import ExternalError
    from rdp.jobs import policy
    from rdp.jobs.gpu import verify_gpu
    from rdp.jobs.logs import JobLog

    mode_path = fake_nvidia_smi.with_name("mode")
    mode_path.write_text("large_stderr", encoding="utf-8")
    path = fake_nvidia_smi.parent / "job.log"
    log = JobLog(path)
    try:
        with pytest.raises(ExternalError) as caught:
            verify_gpu(0, fake_nvidia_smi, log=log)
        objects = {item.key: item.value for item in caught.value.diagnostics[0].objects}
        tail = objects["stderr_tail"]
        assert "尾部已截断" in tail and "模拟长输出 9999" in tail and "模拟长输出 0\n" not in tail
        assert len(tail.encode()) <= policy.PROCESS_STDERR_TAIL_MAX_BYTES
        text = path.read_text(encoding="utf-8")
        assert text.count("stderr nvidia-smi│模拟长输出 ") == 10000
        assert (
            "stderr nvidia-smi│模拟长输出 0\n" in text
            and "stderr nvidia-smi│模拟长输出 9999\n" in text
        )
        mode_path.write_text("timeout", encoding="utf-8")
        monkeypatch.setattr(policy, "GPU_PROBE_TIMEOUT_S", 0.1)
        with pytest.raises(ExternalError) as timed_out:
            verify_gpu(0, fake_nvidia_smi, log=log)
        assert "超时" in timed_out.value.diagnostics[0].actual
    finally:
        log.close()
    for call in fake_nvidia_smi.parent.glob("call-*.json"):
        with pytest.raises(ProcessLookupError):
            os.kill(json.loads(call.read_text(encoding="utf-8"))["pid"], 0)


def test_bad_dependency(fake_nvidia_smi: Path) -> None:
    """契约：非法卡号/相对程序路径/日志依赖为DefectError，工具未启动、现有日志未修改。"""
    from typing import cast

    from rdp.infra.diagnostics import DefectError
    from rdp.jobs.gpu import verify_gpu
    from rdp.jobs.logs import JobLog

    path = fake_nvidia_smi.parent / "unchanged.log"
    log = JobLog(path)
    before = path.read_bytes()
    try:
        for index in (-1, 65536, True, "0", 0.0):
            with pytest.raises(DefectError):
                verify_gpu(cast(int, index), fake_nvidia_smi, log=log)
        for command in (Path("relative"), None, str(fake_nvidia_smi)):
            with pytest.raises(DefectError):
                verify_gpu(0, cast(Path, command), log=log)
        with pytest.raises(DefectError):
            verify_gpu(0, fake_nvidia_smi, log=cast(JobLog, object()))
    finally:
        log.close()
    assert path.read_bytes() == before
    assert not tuple(fake_nvidia_smi.parent.glob("call-*.json"))


def test_all_startup_cards_excluded(fake_nvidia_smi: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """契约：配置卡全部核对失败时有效池为空，需卡作业领取后以平台没有可用的卡外部失败，CPU仍可完成。"""
    from jobs_gpu_support import gpu_case, running_gpu_worker
    from jobs_loop_support import wait_for
    from sqlalchemy import select

    from rdp.infra.db.connection import session_scope
    from rdp.jobs import policy
    from rdp.jobs.scheduling_models import WorkerGpuCheckRow
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    fake_nvidia_smi.with_name("mode").write_text("failure", encoding="utf-8")
    with gpu_case(fake_nvidia_smi.parent / "state", fake_nvidia_smi) as case:
        case.add(71)
        case.add(72, gpu=False)
        with running_gpu_worker(case):
            wait_for(
                lambda: all(case.get(number).state is JobState.COMPLETED for number in (71, 72))
            )
            failed, cpu = case.get(71), case.get(72)
            assert failed.summary is not None and failed.summary.outcome == "failed"
            assert failed.gpu_index is None and failed.wait_reason is None
            assert (
                failed.diagnostics[0].samples[0].category == "external"
                and "没有可用的卡" in failed.diagnostics[0].samples[0].actual
            )
            assert cpu.summary is not None and cpu.summary.outcome == "succeeded"
            with session_scope(case.dependencies.engine, read_only=True) as session:
                assert list(session.scalars(select(WorkerGpuCheckRow.available))) == [False, False]
        text = (case.dependencies.paths.logs / "worker.log").read_text(encoding="utf-8")
        assert text.count("移出本实例名额池") == 2
    assert len(tuple(fake_nvidia_smi.parent.glob("call-*.json"))) == 2


def test_excluded_card_requires_restart(
    fake_nvidia_smi: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """契约：失败卡修好后本实例仍绝不分配，重启再次核对成功才重新入池，不能运行期静默重启用。"""
    from jobs_gpu_support import gpu_case, running_gpu_worker
    from jobs_loop_support import wait_for
    from sqlalchemy import select

    from rdp.infra.db.connection import session_scope
    from rdp.jobs import policy
    from rdp.jobs.scheduling_models import WorkerGpuCheckRow
    from rdp.jobs.types import JobState

    monkeypatch.setattr(policy, "WORKER_POLL_INTERVAL_S", 0.01)
    mode_path = fake_nvidia_smi.with_name("mode")
    mode_path.write_text("missing", encoding="utf-8")
    with gpu_case(fake_nvidia_smi.parent / "state", fake_nvidia_smi, gpus=(1,)) as case:
        case.add(71, gpu=False)
        with running_gpu_worker(case):
            wait_for(lambda: case.get(71).state is JobState.COMPLETED)
            with session_scope(case.dependencies.engine, read_only=True) as session:
                old_instance = session.scalar(select(WorkerGpuCheckRow.instance_id))
            mode_path.write_text("two", encoding="utf-8")
            case.add(72)
            wait_for(lambda: case.get(72).state is JobState.COMPLETED)
            record = case.get(72)
            assert (
                record.summary is not None
                and record.summary.outcome == "failed"
                and record.gpu_index is None
            )
            assert len(tuple(fake_nvidia_smi.parent.glob("call-*.json"))) == 1
        case.add(73)
        with running_gpu_worker(case):
            wait_for(lambda: case.get(73).state is JobState.COMPLETED)
            record = case.get(73)
            assert (
                record.summary is not None
                and record.summary.outcome == "succeeded"
                and record.gpu_index == 1
            )
            with session_scope(case.dependencies.engine, read_only=True) as session:
                check = session.get(WorkerGpuCheckRow, 1)
                assert check is not None and check.available and check.instance_id != old_instance


def test_startup_log_only(fake_nvidia_smi: Path) -> None:
    """契约：启动verify_gpu(log=None)只通过logger写worker.log，不另设核卡文件；作业内核对传当前线程安全JobLog。"""
    from rdp.infra.logging import LoggingSettings, configure_logging
    from rdp.jobs.gpu import verify_gpu
    from rdp.jobs.logs import JobLog

    folder = fake_nvidia_smi.parent / "logs"
    folder.mkdir()
    configure_logging(LoggingSettings("worker", folder, stderr=False))
    verify_gpu(1, fake_nvidia_smi, log=None)
    assert {path.name for path in folder.iterdir()} == {"worker.log"}
    worker_text = (folder / "worker.log").read_text(encoding="utf-8")
    assert "stdout nvidia-smi│0" in worker_text and "stdout nvidia-smi│1" in worker_text
    job_path = folder / "job.log"
    log = JobLog(job_path)
    try:
        verify_gpu(0, fake_nvidia_smi, log=log)
    finally:
        log.close()
    assert (folder / "worker.log").read_text(encoding="utf-8") == worker_text
    assert "stdout nvidia-smi│1" in job_path.read_text(encoding="utf-8")
    calls = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in fake_nvidia_smi.parent.glob("call-*.json")
    ]
    assert len(calls) == 2 and all(
        item["argv"] == ["--query-gpu=index", "--format=csv,noheader,nounits"] for item in calls
    )


def test_optional_command_only_without_configured_cards(tmp_path: Path) -> None:
    """契约：nvidia_smi=None仅在配置gpus为空时合法，配置非空即使预计全部失败也必须注入绝对路径。"""
    from dataclasses import replace
    from threading import Event

    from jobs_gpu_support import gpu_case

    from rdp.infra.diagnostics import DefectError
    from rdp.infra.logging import LoggingSettings
    from rdp.ops.worker import run_worker

    stop = Event()
    stop.set()
    with gpu_case(tmp_path / "configured", tmp_path / "not-executed", gpus=(0,)) as case:
        settings = LoggingSettings("worker", case.dependencies.paths.logs)
        for command in (None, Path("relative")):
            with pytest.raises(DefectError):
                run_worker(
                    case.dependencies,
                    stop,
                    settings,
                    scheduling=replace(case.resources.configuration, nvidia_smi=command),
                )
        assert not case.dependencies.paths.worker_lock.exists()
    with gpu_case(tmp_path / "disabled", tmp_path / "not-executed", gpus=()) as case:
        result = run_worker(
            case.dependencies,
            stop,
            LoggingSettings("worker", case.dependencies.paths.logs),
            scheduling=case.resources.configuration,
        )
        assert result.code == 0 and not result.lock_retained


def test_gpu_checks_persisted_for_instance(tmp_path: Path) -> None:
    """契约：核对通过/移出及诊断原子写worker_gpu_checks，实例标识与心跳关联；失败回滚旧快照，Web不读取内存。"""
    from jobs_progress_support import diagnostic
    from jobs_storage_support import NOW, job_database
    from sqlalchemy import event, select

    from rdp.infra.db.connection import session_scope
    from rdp.infra.diagnostics import (
        DefectError,
        DiagnosticCategory,
        DiagnosticLevel,
        ExternalError,
    )
    from rdp.jobs.resources import save_gpu_checks
    from rdp.jobs.scheduling_models import WorkerGpuCheckRow
    from rdp.jobs.scheduling_types import GpuCheck

    old_id, new_id = "00000000000040008000000000000001", "00000000000040008000000000000002"
    error = diagnostic(1).model_copy(
        update={"category": DiagnosticCategory.EXTERNAL, "level": DiagnosticLevel.ERROR}
    )
    checks = (GpuCheck(0, True, (), NOW), GpuCheck(1, False, (error,), NOW))

    def fail(*args: object) -> None:
        if isinstance(args[2], str) and args[2].startswith("INSERT INTO worker_gpu_checks"):
            raise OSError("模拟插入失败")

    with job_database(tmp_path) as (engine, _paths):
        with session_scope(engine) as session:
            save_gpu_checks(session, old_id, checks)
        with session_scope(engine, read_only=True) as session:
            rows = session.scalars(
                select(WorkerGpuCheckRow).order_by(WorkerGpuCheckRow.gpu_index)
            ).all()
            assert [
                (row.gpu_index, row.instance_id, row.available, row.checked_at) for row in rows
            ] == [(0, old_id, True, NOW), (1, old_id, False, NOW)]
            assert rows[0].diagnostics == [] and rows[1].diagnostics == [
                error.model_dump(mode="json")
            ]
        event.listen(engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(ExternalError), session_scope(engine) as session:
                save_gpu_checks(session, new_id, (checks[0],))
        finally:
            event.remove(engine, "before_cursor_execute", fail)
        with session_scope(engine, read_only=True) as session:
            assert set(session.scalars(select(WorkerGpuCheckRow.instance_id))) == {old_id}
            assert len(session.scalars(select(WorkerGpuCheckRow)).all()) == 2
        with pytest.raises(DefectError), session_scope(engine) as session:
            save_gpu_checks(session, new_id, (GpuCheck(0, True, (error,), NOW),))
        with session_scope(engine) as session:
            save_gpu_checks(session, new_id, ())
        with session_scope(engine, read_only=True) as session:
            assert session.scalars(select(WorkerGpuCheckRow)).all() == []
