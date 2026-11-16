"""手动 Alpha 全链演练：真实预览 → 排除一集 → bwrap 转换 → 四层检查 → 临时入库。

必须用项目 Python 的 -I -B 启动 pytest 并显式指定本文件；basetemp 必须放在本工作树
根目录的 .agibot-drill-* 临时目录内，避免平台 bwrap 的 /tmp tmpfs 遮蔽临时工具登记和状态目录。
不读部署配置、不连真实数据库或服务、不访问真实数据盘；失败保留 pytest 临时现场。
当前 ConversionExecutor 尚需第 04 票的 AgiBot 支持；本演练不会替换执行器弥补缺失能力。
"""

import json
from pathlib import Path
from typing import cast

import pytest
from agibot_alpha_support import (
    DATASET_ID,
    DATASET_NAME,
    SOURCE_ID,
    Drill,
    assemble,
    check_sample_boundary,
    register_real_tool,
    require,
    run_job,
)

from rdp.infra.db.connection import session_scope
from rdp.jobs.cleaning.models import CleaningReport
from rdp.jobs.cleaning.records import read_preview
from rdp.jobs.conversion.ingest_models import APPLY_TYPE, CHECK_TYPE
from rdp.jobs.datasets.models import DatasetRow
from rdp.jobs.navwrite.previews import read_preview as read_ingest_preview
from rdp.jobs.types import JobRecord
from tests.jobs_storage_support import job_database


def _isolate_environment(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """子进程缓存和临时文件全部落在现场目录，工具禁止下载，平台模块显式绑定本工作树。"""
    worktree = Path(__file__).resolve().parents[2]
    require(
        root.resolve().is_relative_to(worktree)
        and root.resolve().relative_to(worktree).parts[0].startswith(".agibot-drill-"),
        "请把 --basetemp 放到本工作树根目录下新建的 .agibot-drill-* 临时目录",
    )
    require(not root.is_symlink(), "演练现场不能是链接")
    for variable, name in (
        ("HOME", "home"),
        ("XDG_CACHE_HOME", "xdg-cache"),
        ("HF_HOME", "hf-home"),
        ("TMPDIR", "tmp"),
    ):
        directory = root / name
        directory.mkdir()
        monkeypatch.setenv(variable, str(directory))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
    # 平台自身受管子进程使用 -m；只提供本工作树的 src，不继承外部 PYTHONPATH。
    monkeypatch.setenv("PYTHONPATH", str(worktree / "src"))


def _selection(report: CleaningReport) -> tuple[list[int], int, str]:
    """从真实报告中排除 650435，体检不通过的缺失集也必须排除，只保留 649806。"""
    usable = [file for file in report.files if not file.fatal_issues]
    require(
        {file.episode_id for file in usable} == {"649806", "650435"},
        "真实报告可转集必须恰好是本地两集",
    )
    retained = next(file for file in usable if file.episode_id == "649806")
    episodes = [episode for episode in report.episodes if episode.file_index == retained.file_index]
    require(len(episodes) == 1, "保留集必须对应报告中的一个完整 episode")
    excluded = [file.file_index for file in report.files if file != retained]
    return excluded, episodes[0].frame_count, retained.path


def _convert(drill: Drill) -> tuple[JobRecord, int]:
    """预览结果直接持久化和消费，转换选择来自报告，不修改工具 JSON 或预览快照。"""
    inputs: dict[str, object] = {
        "dataset_id": DATASET_ID,
        "source_ids": [SOURCE_ID],
        "robot_model": "AgiBot G1",
    }
    preview_job = run_job(drill, "cleaning_preview_agibot2lerobot", inputs)
    with session_scope(drill.engine, read_only=True) as session:
        preview = read_preview(session, preview_job.job_id)
    (drill.paths.root / "清洗预览.json").write_text(preview.model_dump_json(indent=2))
    require(preview.report.source_format == "agibot_native", "预览不是 AgiBot 原生格式")
    excluded, frames, path = _selection(preview.report)
    result = run_job(
        drill,
        "convert_agibot2lerobot",
        {
            **inputs,
            "cleaning_preview_job_id": preview.job_id,
            "output_format": "v3.0",
            "excluded_files": excluded,
            "excluded_episodes": [],
        },
    )
    if result.progress is None or result.progress.conversion is None:
        raise AssertionError("转换缺少产物摘要")
    output = result.progress.conversion
    require((output.total_episodes, output.total_frames) == (1, frames), "产物集数或帧数不符")
    receipt = cast(
        dict[str, object],
        json.loads((Path(output.output_path).parent / "转换回执.json").read_text()),
    )
    receipt_inputs = cast(list[dict[str, object]], receipt["inputs"])
    require([item["path"] for item in receipt_inputs] == [path], "回执必须只包含保留集")
    commands = cast(dict[str, list[str]], receipt["commands"])
    require(
        all("650435" not in arg for args in commands.values() for arg in args),
        "被排除的集不能进入工具转换参数",
    )
    return result, frames


def _check_and_ingest(drill: Drill, converted: JobRecord, frames: int) -> None:
    """真实四层全通过后提交入库，核对移动、两视图链接、血缘和数据库索引。"""
    checked = run_job(
        drill, CHECK_TYPE, {"conversion_job_id": converted.job_id, "automatic": False}
    )
    if checked.progress is None or checked.progress.ingest_check is None:
        raise AssertionError("入库检查没有报告")
    report = checked.progress.ingest_check.report
    require(
        tuple(layer.name for layer in report.layers) == ("结构", "计数", "视频", "内容"),
        "必须完成平台四层检查",
    )
    require(
        all(layer.result == "通过" for layer in report.layers) and report.result == "通过",
        f"检查未全通过，不自动确认警告：{report.model_dump_json()}",
    )
    preview = read_ingest_preview(drill.paths, checked.job_id)
    move = cast(dict[str, object], preview.parameters["move"])
    target = drill.output / str(move["target"])
    original = drill.output / str(move["stage"])
    require(target.resolve().is_relative_to(drill.output), "入库目标越过临时存储根")
    run_job(drill, APPLY_TYPE, {"preview_job_id": checked.job_id})
    require(target.is_dir() and not original.exists(), "真实入库必须完成同根移动")
    _verify_ingested(drill, target, frames, converted.job_id)


def _verify_ingested(drill: Drill, target: Path, frames: int, conversion_id: int) -> None:
    """只读取实际入库产物和导航信息，不以作业成功字段替代结果验证。"""
    name = DATASET_NAME + "_lerobot"
    info = cast(dict[str, object], json.loads((target / "meta/info.json").read_text()))
    require((info["total_episodes"], info["total_frames"]) == (1, frames), "入库产物计数变化")
    rows = [
        cast(dict[str, object], json.loads(line))
        for line in (target / "meta/agibot_episodes.jsonl").read_text().splitlines()
    ]
    require(len(rows) == 1 and str(rows[0]["agibot_episode_id"]) == "649806", "原始集身份不符")
    for relative in (f"按任务/{name}", f"按格式/lerobot/3.0/{name}"):
        entry = drill.nav / relative
        require((entry / "原始数据").readlink() == target, "导航链接未指向真实入库产物")
        information = cast(dict[str, object], json.loads((entry / "数据集信息.json").read_text()))
        with session_scope(drill.engine, read_only=True) as session:
            dataset = session.get(DatasetRow, str(information["dataset_id"]))
            if dataset is None or dataset.name != name:
                raise AssertionError("真实入库未更新数据库索引")
            canonical = dataset.canonical_entry_path
            if canonical is None or canonical != f"按任务/{name}":
                raise AssertionError("入库数据集的规范入口必须是对应的按任务入口")
        # 来源只保存在规范入口；格式视图的副本不承载血缘，读取位置以数据库登记为准。
        provenance = cast(
            dict[str, object], json.loads((drill.nav / canonical / "来源.json").read_text())
        )
        lineage = cast(list[dict[str, object]], provenance["lineage"])
        require(any(row["job_id"] == conversion_id for row in lineage), "缺少本次转换血缘")


def test_alpha_preview_conversion_ingest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """用本地两集 Alpha 样本验证真实平台执行器和入库链路，任何受阻阶段直接失败。

    Args:
        tmp_path: 本工作树 .agibot-drill-* 下的 pytest 独占临时目录，不可复用旧现场。
        monkeypatch: pytest 的环境变量恢复器，只隔离缓存路径，不替换业务实现。

    Returns:
        无；所有实际产物断言通过才算端到端成功。

    Raises:
        AssertionError: 边界、报告、作业、四层检查或真实入库结果不符合要求。
        OSError: 工具或样本不可读、临时目录不可写或 bwrap 被环境阻止。

    Side Effects:
        只读真实工具和获授权本地样本；临时源码副本、数据库、缓存、转换产物、
        导航层和日志全部在 tmp_path；失败现场由 pytest 保留，不访问真实服务。

    Time Semantics:
        顺序执行、遇错即停；沿用真实执行器超时，不重试、不跳过失败阶段。
    """
    check_sample_boundary()
    _isolate_environment(tmp_path, monkeypatch)
    tools = register_real_tool(tmp_path)
    with job_database(tmp_path / "state") as (engine, paths):
        drill = assemble(tmp_path, engine, paths, tools)
        run_job(drill, "dataset_rescan", {})
        converted, frames = _convert(drill)
        _check_and_ingest(drill, converted, frames)
