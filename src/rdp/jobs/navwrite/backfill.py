"""一次性信息回填预览（worker 领域层，M1.5-15、ADR 0006/0008/0009）。

只读导航与索引，生成既有 NavWritePlan，不访问数据链接、不直接写文件。
使用标准库正则和现有 jsonio、指纹、差异报告；第8项解析只属于这次迁移。
"""

import re
from collections.abc import Callable
from functools import partial

from sqlalchemy import select

from rdp.accounts.types import Role
from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.jobs.datasets import _io
from rdp.jobs.datasets.models import SourceRow
from rdp.jobs.datasets.reading import discover_entries, read_entry
from rdp.jobs.datasets.types import EntryLocation, EntrySnapshot, JsonObject, View
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite import _create_read as reads
from rdp.jobs.navwrite._field_diff import differences
from rdp.jobs.navwrite.backfill_parameters import BACKFILL_PREVIEW_TYPE, BackfillParameters
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_external_error, nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild, run_preview
from rdp.jobs.navwrite.jsonio import dump_navigation_json, load_navigation_json
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    NavOperation,
    NavWritePlan,
    PlanReport,
    PreviewState,
    WriteFileStep,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.policy import DATA_ORIGINS
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import RecoveryMode

# 工单第4条只接受整数或整数加一对括号说明；不从自由文字提取数字。
_FPS_TEXT = re.compile(r"([0-9]+)(?:（[^（）()]*）|\([^（）()]*\))?")


def build_backfill_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """登记管理员限定的全量信息回填预览。

    Args:
        dependencies: worker 完整依赖；Web 传 None，仅登记参数和权限。

    Returns:
        无 GPU、并发1、不持导航写锁、可重跑的预览作业定义。

    Raises:
        无。

    Side Effects:
        无；构造时不读取导航或索引。

    Time Semantics:
        启动时登记；实际预览按文件检查取消，确认后由通用写作业持锁复核。
    """
    return JobDefinition(
        BACKFILL_PREVIEW_TYPE,
        "预览回填数据集信息",
        BackfillParameters,
        RecoveryMode.RESTART,
        partial(_execute, dependencies),
        submission_role=Role.ADMINISTRATOR,
    )


def _execute(deps: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """只经公共预览入口持久化计划，缺少 worker 依赖属于装配缺陷。"""
    if deps is None or not isinstance(context.parameters, BackfillParameters):
        raise DefectError()
    run_preview(context, deps, partial(_build, deps))


def _build(deps: NavWriteDependencies, checkpoint: Callable[[], None]) -> PreviewBuild:
    """从导航现场枚举全部身份；索引只用于回退 FPS，不决定迁移范围。"""
    nav = deps.rescan.nav_root
    locations = discover_entries(nav).entries
    ids: set[str] = set()
    for location in locations:
        snapshot = read_entry(nav, location, checkpoint=checkpoint)
        if snapshot.dataset_id is None:
            raise nav_input_error("NAV_BACKFILL", "入口缺少数据集身份，无法完整回填")
        ids.add(snapshot.dataset_id)
    dataset_ids = tuple(sorted(ids))
    state = capture_preview_state(nav, dataset_ids, None, checkpoint=checkpoint)
    steps: list[WriteFileStep] = []
    originals: dict[str, bytes] = {}
    for dataset in state.datasets:
        entries = [
            location
            for location in locations
            if str(location.path) in {item.path for item in dataset.entries}
        ]
        dataset_steps, dataset_originals = _dataset(deps, state, entries, checkpoint)
        steps.extend(dataset_steps)
        originals.update(dataset_originals)
    listed, total = differences(steps, originals, checkpoint)
    verify_preview_state(nav, state, checkpoint=checkpoint)
    return PreviewBuild(
        NavWritePlan(
            operation=NavOperation.EDIT_DATASET_FIELDS,
            dataset_ids=dataset_ids,
            steps=tuple(steps),
            state=state,
        ),
        PlanReport(
            file_count=len(steps),
            link_count=0,
            directory_count=0,
            field_counts=(),
            listed_changes=listed,
            listed_total=total,
            checks=(
                CheckNote(
                    name="信息回填",
                    scope=CheckScope.FULL,
                    detail="全量核对导航指纹；只追加缺失的顶层字段并升级来源文件，格式信息副本由规范副本同步；不访问原始数据",
                ),
            ),
            notices=(),
        ),
        {},
    )


def _fps(information: JsonObject, deps: NavWriteDependencies, entry: str) -> int | None:
    """第8项精确语法优先，回退只取规范入口 LeRobot 的唯一原始帧率。"""
    fields = information.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if (
                not isinstance(field, dict)
                or field.get("number") != 8
                or field.get("name") != "FPS"
            ):
                continue
            text = field.get("value_markdown")
            match = _FPS_TEXT.fullmatch(text.strip()) if isinstance(text, str) else None
            if match is not None and (value := int(match[1])) > 0:
                return value
    with session_scope(deps.rescan.engine, read_only=True) as session:
        # 最多取两种原始值就能判定唯一性；取整沿用索引，不把两种相近帧率误并成一种。
        rates = list(
            session.execute(
                select(SourceRow.fps, SourceRow.fps_rounded)
                .where(
                    SourceRow.entry_path == entry,
                    SourceRow.format == "lerobot",
                    SourceRow.fps.is_not(None),
                    SourceRow.meta_checked_at.is_not(None),
                )
                .distinct()
                .limit(2)
            )
        )
    if len(rates) == 1:
        rounded = rates[0].fps_rounded
        if rounded is not None and rounded > 0:
            return rounded

    return None


def _write(
    steps: list[WriteFileStep], originals: dict[str, bytes], path: str, before: bytes, after: bytes
) -> None:
    """只计划不同字节，差异报告与变更记录前像共用同一原文。"""
    if before != after:
        originals[path] = before
        steps.append(
            WriteFileStep(
                path=path,
                before=plans.image(before),
                after=plans.image(after),
                after_content=after.decode("utf-8"),
            )
        )


def _provenance(
    deps: NavWriteDependencies,
    current: EntrySnapshot,
    state: PreviewState,
    checkpoint: Callable[[], None],
) -> tuple[bytes, JsonObject] | None:
    """以指纹限定原始来源 JSON，保留未知键和血缘，不经版本模型重建。"""
    entry = next(
        item
        for dataset in state.datasets
        for item in dataset.entries
        if item.path == str(current.location.path)
    )
    fingerprint = next(item for item in entry.json_files if item.name == "来源.json")
    if fingerprint.sha256 is None:
        return None
    try:
        with _io.directory(deps.rescan.nav_root / current.location.path) as descriptor:
            raw = _io.read_file(descriptor, "来源.json", checkpoint)
    except OSError as error:
        raise nav_external_error("NAV_BACKFILL", "读取来源文件前像失败") from error
    if plans.image(raw).sha256 != fingerprint.sha256:
        raise nav_conflict_error("NAV_BACKFILL", "来源文件在预览期间变化")
    source = load_navigation_json(raw)
    if source.get("schema_version") not in (1, 2):
        raise nav_input_error("NAV_BACKFILL", "来源文件 schema_version 必须为1或2")
    if (
        source.get("dataset_id") != current.dataset_id
        or source.get("dataset_name") != current.location.dataset_name
    ):
        raise nav_input_error("NAV_BACKFILL", "来源文件身份与规范入口不一致")
    return raw, source


def _dataset(
    deps: NavWriteDependencies,
    state: PreviewState,
    entries: list[EntryLocation],
    checkpoint: Callable[[], None],
) -> tuple[list[WriteFileStep], dict[str, bytes]]:
    """只变更规范信息和来源，信息整份同步格式副本，其他导航文件不参与回填。"""
    nav = deps.rescan.nav_root
    steps: list[WriteFileStep] = []
    originals: dict[str, bytes] = {}
    canonical = [location for location in entries if location.view is View.TASK]
    if len(canonical) != 1:
        raise nav_input_error("NAV_BACKFILL", "数据集必须有唯一规范入口")
    current, raw = reads.snapshot(nav, canonical[0], state, checkpoint)
    if any(
        doc.payload is None or doc.payload.get("dataset_id") != current.dataset_id
        for doc in current.documents
    ):
        raise nav_input_error("NAV_BACKFILL", "规范入口基础 JSON 身份不一致")
    information = dict(plans.payload(current, 1))
    if "fps" not in information:
        fps = _fps(information, deps, str(current.location.path))
        if fps is not None:
            information["fps"] = fps
    provenance = _provenance(deps, current, state, checkpoint)
    if provenance is not None:
        source_raw, source = provenance
        previous_source = dict(source)
        _migrate_origin(information, source)
        _write(
            steps,
            originals,
            str(current.location.path / "来源.json"),
            source_raw,
            dump_navigation_json(source) if source != previous_source else source_raw,
        )
    # 没有新增键时连序列化空白也保留；实际修改仍按既有 jsonio 格式写出。
    after = (
        dump_navigation_json(information)
        if information != plans.payload(current, 1)
        else raw["数据集信息.json"]
    )
    _write(
        steps,
        originals,
        str(current.location.path / "数据集信息.json"),
        raw["数据集信息.json"],
        after,
    )
    for location in entries:
        if location.view is View.FORMAT:
            _, previous = reads.snapshot(nav, location, state, checkpoint)
            # L8：信息文件整份复制规范副本；迁移不重建无关的清单与子任务文件。
            _write(
                steps,
                originals,
                str(location.path / "数据集信息.json"),
                previous["数据集信息.json"],
                after,
            )
    return steps, originals


def _migrate_origin(information: JsonObject, source: JsonObject) -> None:
    """在原始对象上迁移来源，禁止模型补默认值或重建血缘。"""
    if "data_origin" not in information and source["schema_version"] == 1:
        origin = source.get("data_origin")
        if origin not in DATA_ORIGINS:
            raise nav_input_error("NAV_BACKFILL", "第1版来源的数据来源不在取值表中")
        information["data_origin"] = origin
    source.pop("data_origin", None)
    source.pop("data_origin_set_by", None)
    source["schema_version"] = 2
