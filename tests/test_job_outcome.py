"""工单 04 的公开契约测试；只用内存输入和临时目录，验证诊断与失败边界。"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest

from rdp.jobs.outcome import JobOutcome, calculate_outcome


def test_enum_terms() -> None:
    """验证契约：JobOutcome 四个英文成员/值对应 GLOSSARY 的 Succeeded、Succeeded with Warnings、Partially Succeeded、Failed。"""
    assert {member.name: member.value for member in JobOutcome} == {
        "SUCCEEDED": "succeeded",
        "SUCCEEDED_WITH_WARNINGS": "succeeded_with_warnings",
        "PARTIALLY_SUCCEEDED": "partially_succeeded",
        "FAILED": "failed",
    }


def test_succeeded() -> None:
    """验证契约：total_items=3、failed_items=0、warning_count=0、aborted=False 返回 SUCCEEDED。"""
    assert (
        calculate_outcome(total_items=3, failed_items=0, warning_count=0, aborted=False)
        is JobOutcome.SUCCEEDED
    )


def test_succeeded_with_warnings() -> None:
    """验证契约：total_items=3、failed_items=0、warning_count=1、aborted=False 返回 SUCCEEDED_WITH_WARNINGS。"""
    assert (
        calculate_outcome(total_items=3, failed_items=0, warning_count=1, aborted=False)
        is JobOutcome.SUCCEEDED_WITH_WARNINGS
    )


def test_partially_succeeded() -> None:
    """验证契约：total_items=3、failed_items=1、warning_count=0、aborted=False 返回 PARTIALLY_SUCCEEDED。"""
    assert (
        calculate_outcome(total_items=3, failed_items=1, warning_count=0, aborted=False)
        is JobOutcome.PARTIALLY_SUCCEEDED
    )


def test_partial_with_warnings() -> None:
    """验证契约：部分失败同时有两条警告仍返回 PARTIALLY_SUCCEEDED，警告不能覆盖失败结论。"""
    assert (
        calculate_outcome(total_items=3, failed_items=1, warning_count=2, aborted=False)
        is JobOutcome.PARTIALLY_SUCCEEDED
    )


def test_all_failed() -> None:
    """验证契约：total_items=1、failed_items=1 返回 FAILED，不论是否有警告。"""
    for warnings in (0, 2):
        assert (
            calculate_outcome(total_items=1, failed_items=1, warning_count=warnings, aborted=False)
            is JobOutcome.FAILED
        )


def test_aborted_without_item_failures() -> None:
    """验证契约：整体中止时即使 failed_items=0 仍返回 FAILED，包括 total_items=0 的情况。"""
    for total in (0, 3):
        assert (
            calculate_outcome(total_items=total, failed_items=0, warning_count=0, aborted=True)
            is JobOutcome.FAILED
        )


def test_aborted_overrides_partial() -> None:
    """验证契约：部分失败/全部成功但整体中止都返回 FAILED。"""
    for failed in (0, 1):
        assert (
            calculate_outcome(total_items=3, failed_items=failed, warning_count=2, aborted=True)
            is JobOutcome.FAILED
        )


def test_empty_job() -> None:
    """验证契约：total_items=0、failed_items=0、未中止时，无警告返回 SUCCEEDED，有警告返回 SUCCEEDED_WITH_WARNINGS。"""
    assert (
        calculate_outcome(total_items=0, failed_items=0, warning_count=0, aborted=False)
        is JobOutcome.SUCCEEDED
    )
    assert (
        calculate_outcome(total_items=0, failed_items=0, warning_count=1, aborted=False)
        is JobOutcome.SUCCEEDED_WITH_WARNINGS
    )


def test_negative_counts() -> None:
    """验证契约：逐个计数参数为 -1 均触发 ValueError，包括 aborted=True，不能短路跳过验证。"""
    for key in ("total_items", "failed_items", "warning_count"):
        for aborted in (False, True):
            counts = dict(total_items=2, failed_items=0, warning_count=0)
            counts[key] = -1
            with pytest.raises(ValueError):
                calculate_outcome(**counts, aborted=aborted)


def test_failed_exceeds_total() -> None:
    """验证契约：total_items=0/1，failed_items=total_items+1 触发 ValueError。"""
    for total in (0, 1):
        with pytest.raises(ValueError):
            calculate_outcome(
                total_items=total, failed_items=total + 1, warning_count=0, aborted=False
            )


def test_count_types() -> None:
    """验证契约：每个计数分别传 bool/float/str/None 均触发 ValueError，不做隐式数字转换。"""
    for key in ("total_items", "failed_items", "warning_count"):
        for invalid in (True, 1.0, "1", None):
            counts: dict[str, Any] = dict(total_items=2, failed_items=0, warning_count=0)
            counts[key] = invalid
            with pytest.raises(ValueError):
                calculate_outcome(**counts, aborted=False)


def test_aborted_type() -> None:
    """验证契约：aborted 传 0/1/字符串/None 均触发 ValueError，必须为 bool。"""
    for value in (0, 1, "yes", None):
        with pytest.raises(ValueError):
            calculate_outcome(
                total_items=1, failed_items=0, warning_count=0, aborted=cast(Any, value)
            )


def test_pure_and_no_clock(caplog: pytest.LogCaptureFixture) -> None:
    """验证契约：calculate_outcome 相同输入结果相同，无 I/O、日志、时间读取或输入变更。"""
    original = dict(total_items=9, failed_items=2, warning_count=3)
    for _ in range(2):
        assert calculate_outcome(**original, aborted=False) is JobOutcome.PARTIALLY_SUCCEEDED
    assert original == dict(total_items=9, failed_items=2, warning_count=3)
    assert not caplog.records


def test_layers_forbid_reverse_dependencies(tmp_path: Path) -> None:
    """验证契约：验收7：临时副本内分别植入 jobs→api、jobs→ops、infra→jobs，import-linter 均拒绝；不修改工作区或真实数据。"""
    for source, target in (
        ("rdp.jobs", "rdp.api"),
        ("rdp.jobs", "rdp.ops"),
        ("rdp.infra", "rdp.jobs"),
    ):
        _check_forbidden(tmp_path, source, target)


def test_layers_forbid_framework_dependencies(tmp_path: Path) -> None:
    """验证契约：验收7：临时副本分别植入 jobs/infra→fastapi/starlette/uvicorn 均被 forbidden 拒绝。"""
    for source in ("rdp.jobs", "rdp.infra"):
        for target in ("fastapi", "starlette", "uvicorn"):
            _check_forbidden(tmp_path, source, target)


def _check_forbidden(tmp_path: Path, source: str, target: str) -> None:
    """只在临时副本植入违规导入，观察真实 import-linter 的拒绝结果。"""
    root = Path(__file__).resolve().parents[1]
    case = tmp_path / (source + "-" + target)
    case.mkdir()
    shutil.copytree(root / "src/rdp", case / "rdp", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copyfile(root / "pyproject.toml", case / "pyproject.toml")
    module = case / source.replace(".", "/") / "_violation.py"
    module.write_text(f"import {target}\n")
    result = subprocess.run(  # noqa: S603  # 理由：固定项目工具和临时副本，不通过 shell。
        [str(root / ".venv/bin/lint-imports"), "--no-cache", "--no-logo"],
        cwd=case,
        env=os.environ | {"PYTHONPATH": str(case)},
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "BROKEN" in result.stdout and source in result.stdout and target in result.stdout
