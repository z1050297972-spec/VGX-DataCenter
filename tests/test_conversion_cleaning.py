"""M4.5-03 关键契约：假工具与假 LeRobot 的真实子进程，观察执行结果、回执和 HTTP。"""

import json
import os
import shutil
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from account_api_support import add_actor
from conversion_cleaning_support import fake_lerobot, seed_preview
from conversion_support import fake_converter, no_sandbox, settings, storage_checker
from dataset_api_support import browser_case
from datasets_execution_support import dataset_case
from jobs_execution_support import execution_case
from nav_manifest import FakeNavigation
from pydantic import SecretStr
from sqlalchemy import Engine
from tool_registry_support import ToolFiles
from tool_registry_support import isolated_tool_cache as isolated_tool_cache

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DiagnosticCategory
from rdp.jobs.cleaning.records import CleaningPreviewRow, read_preview
from rdp.jobs.conversion import lerobot
from rdp.jobs.conversion._cleaning import problem
from rdp.jobs.conversion.job import ConversionDependencies, ConversionExecutor
from rdp.jobs.conversion.parameters import ConversionParameters, EpisodeSelection
from rdp.jobs.conversion.registration import register_conversion_jobs
from rdp.jobs.execution import ExecutionContext, execute_job
from rdp.jobs.outcome import JobOutcome
from rdp.jobs.registry import production_registry
from rdp.jobs.types import JobRecord


@dataclass
class CleaningConversionCase:
    """单次转换的可观察外部边界，全部文件和数据库在临时根。"""

    root: Path
    engine: Engine
    files: ToolFiles
    parameters: ConversionParameters
    dependencies: ConversionDependencies
    python: Path
    inputs: tuple[Path, ...]

    def run(self) -> JobRecord:
        """经框架运行，保留真实进程、诊断、取消与资源回收逻辑。"""

        def execute(context: ExecutionContext) -> None:
            ConversionExecutor("mcap2lerobot", self.dependencies).execute(
                replace(context, parameters=self.parameters)
            )

        with execution_case(self.root / "state", {"steps": 1, "interval_ms": 0}, execute) as (
            work,
            deps,
            signals,
        ):
            result = execute_job(work, deps, signals)
            assert result is not None
            assert all(not thread.is_alive() for thread in signals.monitor.threads)
            return result

    @property
    def stage(self) -> Path:
        """本次固定测试作业编号对应的暂存位置。"""
        return self.root / "output/暂存/转换/71"


@contextmanager
def cleaning_case(
    root: Path,
    fake: FakeNavigation,
    monkeypatch: pytest.MonkeyPatch,
    *,
    output_lengths: tuple[int, ...] = (2, 3, 4, 5),
    encoder_crf: int = 30,
) -> Generator[CleaningConversionCase]:
    """三文件五段：剔除首文件后，最后文件的首段从原编号3前移到2。"""
    files = fake_converter(root / "tool", lengths=output_lengths)
    # 预览前修改临时登记配置，证明删除参数来自转换所用文件而非写死的 R1 Lite 值。
    config = files.package / "configs/r1lite.toml"
    config.write_text(config.read_text().replace("crf = 30", f"crf = {encoder_crf}"))
    source = (
        fake.storage_roots[1].path / "R1_lite_table_withdrawing_mcap/20261009_table_withdrawing"
    )
    inputs = tuple(source / name for name in ("a.mcap", "b.mcap", "c.mcap"))
    for path in inputs:
        path.write_bytes(b"mcap")
    output = root / "output"
    output.mkdir()
    python, registration = fake_lerobot(root / "lerobot")
    monkeypatch.setattr(lerobot, "ENV_DIRECTORY", registration)
    with dataset_case(root / "index", fake) as scan:
        scan.run()
        parameters = seed_preview(
            scan.engine,
            files,
            ConversionParameters(
                dataset_id="dataset-35",
                source_ids=["src_01e0bc7e9cc8"],
                robot_model="Galaxea R1 Lite",
                output_format="v3.0",
                excluded_files=[0],
            ),
            lengths=((9,), (2, 3), (4, 5)),
        )
        roots = (
            *fake.storage_roots,
            StorageRootConfig(
                name="output", path=output, nfs_export="server:/output", writable=True
            ),
        )
        dependencies = ConversionDependencies(
            scan.engine,
            settings(files).model_copy(update={"lerobot_python": python}),
            roots,
            no_sandbox,
            storage=storage_checker(roots),
        )
        yield CleaningConversionCase(
            root, scan.engine, files, parameters, dependencies, python, inputs
        )


@pytest.mark.parametrize("version", ["v3.0", "v2.1"])
def test_selected_files_are_ordered_and_no_lerobot_is_required(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch, version: str
) -> None:
    """范围1/5：只传未剔除文件，两个产物版本均逐段匹配，无删除时不要求解释器。"""
    with cleaning_case(tmp_path, fake_nav, monkeypatch) as case:
        case.parameters = case.parameters.model_copy(update={"output_format": version})
        case.dependencies = replace(
            case.dependencies,
            tools=case.dependencies.tools.model_copy(update={"lerobot_python": None}),
        )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        assert json.loads(case.files.program.with_suffix(".inputs").read_text()) == [
            str(path) for path in case.inputs[1:]
        ]
        assert result.progress is not None and result.progress.conversion is not None
        assert result.progress.conversion.output_path == str(case.stage / "out")
        assert not case.python.with_suffix(".calls").exists()
        cleaning = json.loads((case.stage / "转换回执.json").read_text())["cleaning"]
        assert cleaning["encoder"] is None


def test_episode_deletion_uses_shifted_indices_and_cleaned_result(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """范围2及07范围2/3：段号前移；脚本使用登记编码器并恢复工厂，命令与回执一致。"""
    with cleaning_case(tmp_path, fake_nav, monkeypatch, encoder_crf=21) as case:
        case.parameters = case.parameters.model_copy(
            update={"excluded_episodes": [EpisodeSelection(file_index=2, segment_index=0)]}
        )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.SUCCEEDED
        encoder = {
            "vcodec": "hevc_nvenc",
            "pix_fmt": "yuv420p",
            "options": {"g": "2", "bf": "0", "rc": "constqp", "qp": "21"},
        }
        assert json.loads(case.python.with_suffix(".calls").read_text()) == {
            "episodes": [2],
            "encoder": encoder,
        }
        assert json.loads(case.python.with_suffix(".restored").read_text()) is True
        assert result.progress is not None and result.progress.conversion is not None
        assert result.progress.conversion.output_path == str(case.stage / "cleaned")
        assert result.progress.conversion.total_episodes == 3
        assert result.progress.conversion.total_frames == 10
        cleaning = json.loads((case.stage / "转换回执.json").read_text())["cleaning"]
        assert cleaning["cleaning_preview_job_id"] == 59
        assert cleaning["excluded_files"] == [
            {"file_index": 0, "path": str(case.inputs[0]), "reason": "用户选择剔除"}
        ]
        assert cleaning["excluded_episodes"] == [
            {"file_index": 2, "segment_index": 0, "episode_index": 2, "reason": "用户选择剔除"}
        ]
        assert cleaning["lerobot_version"] == "0.6.2"
        assert len(cleaning["lerobot_fingerprint"]) == 64
        assert cleaning["command"][-1] == "2"
        assert cleaning["encoder"] == encoder
        command = cleaning["command"]
        assert json.loads(command[command.index("--encoder") + 1]) == encoder
        with session_scope(case.engine, read_only=True) as session:
            preview = read_preview(session, 59)
        assert cleaning["config_sha256"] == preview.config_sha256
        assert cleaning["rules_sha256"] == preview.rules_sha256


@pytest.mark.parametrize("change", ["mtime", "missing_preview"])
def test_modified_input_fails_before_staging(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """范围3及执行门禁：mtime变动或没有预览都是输入问题，不建暂存且不调用工具。"""
    with cleaning_case(tmp_path, fake_nav, monkeypatch) as case:
        path = case.inputs[1]
        stat = path.stat()
        if change == "mtime":
            os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1))
            expected = "请重新清洗预览"
        else:
            case.parameters = case.parameters.model_copy(update={"cleaning_preview_job_id": None})
            expected = "转换必须从清洗预览发起"
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        samples = [sample for group in result.diagnostics for sample in group.samples]
        assert any(
            item.category is DiagnosticCategory.INPUT and expected in item.actual
            for item in samples
        )
        assert not case.stage.exists()
        assert not case.files.program.with_suffix(".calls").exists()


def test_output_mismatch_stops_before_deletion(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """范围4：第二段帧数错一帧，给出第一处差异，不调用LeRobot，原产物保留。"""
    with cleaning_case(tmp_path, fake_nav, monkeypatch, output_lengths=(2, 4, 4, 5)) as case:
        case.parameters = case.parameters.model_copy(
            update={"excluded_episodes": [EpisodeSelection(file_index=2, segment_index=0)]}
        )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        diagnostic = next(
            sample
            for group in result.diagnostics
            for sample in group.samples
            if sample.rule == "cleaning.output_mismatch"
        )
        assert diagnostic.category is DiagnosticCategory.EXTERNAL
        assert "episode 1 帧数 4，预览 3" in diagnostic.actual
        assert ("path", str(case.stage / "out")) in [
            (item.key, item.value) for item in diagnostic.objects
        ]
        assert "不入库" in diagnostic.consequence
        assert (case.stage / "out").exists()
        assert not case.python.with_suffix(".calls").exists()


@pytest.mark.parametrize("failure", ["mismatch", "unconfigured"])
def test_unusable_lerobot_refuses_deletion(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """范围5：源码指纹不符和未配置都以输入问题拒绝，绝不调用删除脚本。"""
    with cleaning_case(tmp_path, fake_nav, monkeypatch) as case:
        case.parameters = case.parameters.model_copy(
            update={"excluded_episodes": [EpisodeSelection(file_index=2, segment_index=0)]}
        )
        if failure == "mismatch":
            (case.python.parent / "package/datasets/read.py").write_text("# changed\n")
        else:
            case.dependencies = replace(
                case.dependencies,
                tools=case.dependencies.tools.model_copy(update={"lerobot_python": None}),
            )
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        expected = (
            "LeRobot 环境已变化，需要重新登记" if failure == "mismatch" else "未配置 LeRobot 环境"
        )
        assert any(
            sample.category is DiagnosticCategory.INPUT and expected in sample.actual
            for group in result.diagnostics
            for sample in group.samples
        )
        assert not case.python.with_suffix(".calls").exists()
        if failure == "unconfigured":
            assert not case.stage.exists()


@pytest.mark.parametrize(
    "choice", ["fatal", "all", "all_episodes", "foreign", "redundant", "valid"]
)
def test_preview_convert_validates_final_selection(
    tmp_path: Path, fake_nav: FakeNavigation, choice: str
) -> None:
    """范围6：HTTP拒绝致命文件未剔除、全部剔除、越界与冗余身份；合法选择原样保存。"""
    files = fake_converter(tmp_path / "tool")
    registry = production_registry()
    register_conversion_jobs(registry, settings(files), fake_nav.storage_roots, None)
    with browser_case(tmp_path / "state", fake_nav, registry=registry) as api:
        parameters = seed_preview(
            api.engine,
            files,
            ConversionParameters(
                dataset_id="dataset-35",
                source_ids=["src_01e0bc7e9cc8", "src_d5edab567d18"],
                robot_model="Galaxea R1 Lite",
            ),
        )
        payload: dict[str, object] = {"excluded_files": [], "excluded_episodes": []}
        if choice == "fatal":
            with session_scope(api.engine) as session:
                row = session.get(CleaningPreviewRow, parameters.cleaning_preview_job_id)
                assert row is not None
                report = read_preview(session, 59).report
                first = report.files[0].model_copy(update={"fatal_issues": (problem("话题缺失"),)})
                row.report = report.model_copy(
                    update={"files": (first, *report.files[1:])}
                ).model_dump(mode="json")
        elif choice == "all":
            payload["excluded_files"] = [0, 1]
        elif choice == "all_episodes":
            payload["excluded_episodes"] = [
                {"file_index": 0, "segment_index": 0},
                {"file_index": 1, "segment_index": 0},
            ]
        elif choice == "foreign":
            payload["excluded_files"] = [99]
        elif choice == "redundant":
            payload.update(
                excluded_files=[0], excluded_episodes=[{"file_index": 0, "segment_index": 0}]
            )
        else:
            payload["excluded_files"] = [0]
        response = api.client.post("/api/cleaning-previews/59/convert", json=payload)
        assert response.status_code == (201 if choice == "valid" else 422), response.text
        if choice == "valid":
            actual = response.json()["parameters"]
            assert actual["cleaning_preview_job_id"] == 59
            assert actual["excluded_files"] == [0]
            assert actual["excluded_episodes"] == []
            assert actual["output_format"] == "v3.0"
        assert api.client.post("/api/jobs/convert/mcap2lerobot", json={}).status_code == 404


def test_member_cannot_convert_from_preview(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """范围6：成员被全局鉴权拒绝，先于预览查找和参数校验。"""
    files = fake_converter(tmp_path / "tool")
    registry = production_registry()
    register_conversion_jobs(registry, settings(files), fake_nav.storage_roots, None)
    with browser_case(tmp_path / "state", fake_nav, registry=registry) as api:
        add_actor(api)
        assert api.login("member", SecretStr("member-updated-value")).status_code == 200
        assert api.client.post("/api/cleaning-previews/59/convert", json={}).status_code == 403


def test_deletion_space_estimate_includes_both_products(
    tmp_path: Path, fake_nav: FakeNavigation, monkeypatch: pytest.MonkeyPatch
) -> None:
    """范围2的空间约束：未剔除两文件8字节，100%乘两倍需16字节，只有15字节必须拒绝。"""
    with cleaning_case(tmp_path, fake_nav, monkeypatch) as case:
        case.parameters = case.parameters.model_copy(
            update={
                "excluded_episodes": [EpisodeSelection(file_index=2, segment_index=0)],
                "space_ratio_percent": 100,
                "space_reserve_gib": 0,
            }
        )

        def disk_usage(path: Path) -> SimpleNamespace:
            return SimpleNamespace(free=15)

        monkeypatch.setattr(shutil, "disk_usage", disk_usage)
        result = case.run()
        assert result.summary is not None and result.summary.outcome is JobOutcome.FAILED
        diagnostic = next(
            sample
            for group in result.diagnostics
            for sample in group.samples
            if sample.rule == "conversion.insufficient_space"
        )
        assert "输入 8 字节" in diagnostic.actual
        assert "估算产物 16 字节" in diagnostic.actual
        assert "工具产物 + 清洗后副本" in diagnostic.actual
        assert not case.stage.exists()
        assert not case.files.program.with_suffix(".calls").exists()
