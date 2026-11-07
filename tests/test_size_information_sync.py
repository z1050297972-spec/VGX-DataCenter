"""M1.5-17 大小文字与自动写入验收，只使用临时导航层。"""

import json
import time
from dataclasses import replace
from datetime import date
from pathlib import Path
from threading import Event, Lock
from zoneinfo import ZoneInfo

import pytest
from datasets_storage_support import enable_storage
from jobs_scheduling_support import claim_fixture, resources_fixture
from jobs_storage_support import NOW
from nav_manifest import FakeNavigation
from navwrite_pipeline_support import Harness, harness, job_rows
from navwrite_support import tree_state
from sqlalchemy import select

from rdp.audit.models import OperationLogRow
from rdp.audit.types import OperationDetails
from rdp.infra.db.connection import session_scope
from rdp.jobs.datasets._size_text import format_size_text, parse_size_bytes
from rdp.jobs.execution import ExecutionContext, ExecutionWork, ExecutorDependencies, execute_job
from rdp.jobs.navwrite.changes import read_change_record
from rdp.jobs.navwrite.jsonio import load_navigation_json
from rdp.jobs.progress import ExecutionMonitor, ExecutionSignals
from rdp.jobs.records import claim_job
from rdp.jobs.registry import JobRegistry, production_registry
from rdp.jobs.types import ExecutionMode, JobClock, JobRecord


@pytest.mark.parametrize(
    ("size_bytes", "prefix"),
    [
        (631_143_349, "0.63 GB（631,143,349 B；"),
        (119_642_823_842, "119.64 GB（119,642,823,842 B；"),
        (999_999_999_999, "1000.00 GB（999,999,999,999 B；"),
        (1_000_000_000_000, "1000.00 GB / 1.00 TB（1,000,000,000,000 B；"),
    ],
)
def test_size_text_contract(size_bytes: int, prefix: str) -> None:
    """不到1 TB只写GB，达到阈值才附TB；按原始字节判定，两种文字都能解析。"""
    expected = prefix + "LeRobot 只计 parquet、mp4 和 meta，其他格式计全部文件；统计于 2026-11-06）"
    assert format_size_text(size_bytes, date(2026, 11, 6)) == expected
    assert parse_size_bytes(expected) == size_bytes


def test_size_text_parsing_remains_compatible() -> None:
    """解析规则不变：旧双单位文字仍可读取，只认字节片段，不猜自由文字。"""
    assert parse_size_bytes("119.64 GB / 0.12 TB（119,642,823,842 B；旧说明）") == 119_642_823_842
    assert parse_size_bytes("大小（119642823842 B；说明）") == 119_642_823_842
    assert parse_size_bytes("原来约 119 GB") is None


@pytest.mark.parametrize("old_text", ["旧自由文字", "0 GB（1 B；旧说明）"])
def test_size_sync_roundtrip(tmp_path: Path, fake_nav: FakeNavigation, old_text: str) -> None:
    """旧文字或不同大小会更新；其他字节保留、日期按调度时区、格式副本同步、幂等并保留变更记录。"""
    with harness(tmp_path, fake_nav) as h:
        enable_storage(h.case)
        path, original = _information(h, "libero_10", old_text)
        h.case.run()
        registry = _registry(h)
        _size(h, registry, "dataset-14")
        queued = [row for row in job_rows(h) if row.type_name == "nav_size_sync"]
        assert len(queued) == 1 and queued[0].submitter_name == "系统"
        sync = registry.lookup("nav_size_sync")
        assert sync is not None and sync.writes_navigation
        written = _run_queued(h, registry, queued[0].job_id)
        fields = load_navigation_json(path.read_bytes())["fields"]
        assert isinstance(fields, list) and isinstance(fields[0], dict)
        new = fields[0]["value_markdown"]
        # UTC 26日12点在注入的太平洋 +14 时区已经是27日，不依赖运行测试的机器时区。
        assert isinstance(new, str) and "统计于 2026-10-27" in new
        assert path.read_bytes() == original.replace(
            json.dumps(old_text).encode(), json.dumps(new, ensure_ascii=False).encode(), 1
        )
        assert (
            h.nav / "按格式/lerobot/3.0/libero_10/数据集信息.json"
        ).read_bytes() == path.read_bytes()
        _assert_automatic_audit(h, written.job_id)
        _size(h, registry, "dataset-14")
        assert len([row for row in job_rows(h) if row.type_name == "nav_size_sync"]) == 1


def test_offline_does_not_sync(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """存储根离线时保留第4项和格式副本，且不排队任何自动写入。"""
    with harness(tmp_path, fake_nav) as h:
        _information(h, "libero_10", "旧大小")
        enable_storage(h.case)
        h.case.run()
        enable_storage(h.case, table="")
        before = tree_state(h.nav)
        result = _size(h, _registry(h), "dataset-14")
        assert result.summary is not None and result.summary.warning_count == 1
        assert not [row for row in job_rows(h) if row.type_name == "nav_size_sync"]
        assert tree_state(h.nav) == before


def test_batch_skips_concurrent_edit(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """全量统计只提交一个同步；等待期间有编辑的数据集跳过，其他数据集正常写且可撤回记录准确。"""
    with harness(tmp_path, fake_nav) as h:
        changed, original = _information(h, "libero_10", "旧大小")
        untouched, other_original = _information(h, "EgoProDemo", "旧大小")
        enable_storage(h.case)
        h.case.run()
        registry = _registry(h)
        _size(h, registry, None)
        queued = [row for row in job_rows(h) if row.type_name == "nav_size_sync"]
        assert len(queued) == 1
        changed.write_bytes(original + b"\n")
        result = _run_queued(h, registry, queued[0].job_id)
        assert result.summary is not None and result.summary.warning_count == 0
        assert changed.read_bytes() == original + b"\n"
        assert untouched.read_bytes() != other_original
        record = read_change_record(h.case.paths, result.job_id)
        assert "dataset-14" not in record.dataset_ids


def _information(h: Harness, name: str, old_text: str) -> tuple[Path, bytes]:
    """非标准空白、转义和同值字符串揭露整份重序列化或全局替换。"""
    path = h.nav / "按任务" / name / "数据集信息.json"
    payload = load_navigation_json(path.read_bytes())
    payload["fields"] = [
        {"number": 4, "name": "数据大小", "value_markdown": old_text, "extra": "保留"},
        {"number": 5, "name": "其他", "value_markdown": old_text},
    ]
    original = json.dumps(payload, ensure_ascii=True, indent=3).encode() + b"  \n"
    path.write_bytes(original)
    return path, original


def _registry(h: Harness) -> JobRegistry:
    """注入和调度一致的时区能力；完整装配队列与写入依赖。"""
    deps = replace(h.dependencies, rescan=h.case.scanning, timezone=ZoneInfo("Pacific/Kiritimati"))
    return production_registry(h.case.scanning, deps)


def _size(h: Harness, registry: JobRegistry, dataset_id: str | None) -> JobRecord:
    """统计上下文不提供导航写锁，防止同步接入意外让统计本身拿锁。"""
    definition = registry.lookup("dataset_sizing")
    assert definition is not None
    h.case.number = max([h.case.number, *(row.job_id + 1 for row in job_rows(h))])

    def execute(context: ExecutionContext) -> None:
        definition.execute(replace(context, _navigation=None))

    result = h.case.run(dataset_id, definition=replace(definition, execute=execute))
    assert result.summary is not None and not result.summary.aborted, result.diagnostics
    return result


def _assert_automatic_audit(h: Harness, job_id: int) -> None:
    """写入日志须有真实系统身份、平台自动摘要和变更记录引用。"""
    with session_scope(h.case.engine, read_only=True) as session:
        audits = list(
            session.scalars(
                select(OperationLogRow).where(
                    OperationLogRow.object_kind == "navigation_write",
                    OperationLogRow.object_id == str(job_id),
                )
            )
        )
        assert len(audits) == 1
        assert audits[0].actor_id is None and audits[0].actor_name == "系统"
        assert "平台自动" in audits[0].object_name
        details = OperationDetails.model_validate(audits[0].details)
        assert details.after.change_record_id == str(job_id)


def _run_queued(h: Harness, registry: JobRegistry, job_id: int) -> JobRecord:
    """以真实系统身份领取自动作业，复用框架锁、执行与恢复声明。"""
    with session_scope(h.case.engine) as session:
        record = claim_job(session, job_id, now=NOW, paths=h.case.paths, gpu_index=None)
    dependencies = ExecutorDependencies(
        h.case.engine,
        registry,
        h.case.paths,
        JobClock(lambda: NOW, time.monotonic),
        resources=resources_fixture(registry),
        storage=None,
    )
    work = ExecutionWork(
        record, ExecutionMode.FRESH, None, claim=claim_fixture(record, dependencies)
    )
    result = execute_job(
        work, dependencies, ExecutionSignals(Event(), Event(), ExecutionMonitor([], None, Lock()))
    )
    assert result is not None
    assert result.summary is not None and not result.summary.aborted, result.diagnostics
    return result
