"""数据来源预览作业（worker 领域层，M1-10、ADR 0008/0009）。

复用第 07 张的来源模型、指纹、预览存储和写入流水线；本模块只生成一条写文件计划，
不自行写导航层，不访问链接目标。JSON、哈希、校验使用标准库及已有 Pydantic，不新增依赖。
"""

import hashlib
import json
from collections.abc import Callable
from functools import partial
from pathlib import PurePosixPath

from rdp.infra.db.connection import session_scope
from rdp.infra.diagnostics import DefectError
from rdp.infra.timeutil import ensure_utc
from rdp.jobs.datasets import _io
from rdp.jobs.datasets.reading import read_entry
from rdp.jobs.datasets.types import EntryLocation, JsonObject, ProvenanceState, View
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.navwrite.errors import nav_conflict_error, nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild, run_preview
from rdp.jobs.navwrite.jsonio import dump_navigation_json
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    FileImage,
    ListedChange,
    NavOperation,
    NavWritePlan,
    PlanReport,
    WriteFileStep,
)
from rdp.jobs.navwrite.origin_parameters import DATA_ORIGIN_PREVIEW_TYPE, DataOriginParameters
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.preview_state import capture_preview_state
from rdp.jobs.navwrite.provenance import (
    ActorStamp,
    dump_provenance,
    new_provenance,
    read_provenance,
    with_data_origin,
)
from rdp.jobs.records import find_job
from rdp.jobs.registry import JobDefinition
from rdp.jobs.types import ExecutionMode, RecoveryMode


def build_data_origin_definition(dependencies: NavWriteDependencies | None) -> JobDefinition:
    """构造只读的数据来源预览作业定义。

    Args:
        dependencies: worker 的写入依赖；Web 登记传 None，只获得参数校验能力。

    Returns:
        nav_data_origin_preview，恢复方式 RESTART，并发 1，无 GPU，不声明存储根、不持写锁。

    Raises:
        无。

    Side Effects:
        无；只构造定义，不读配置、文件或数据库。

    Time Semantics:
        Web 与 worker 启动时各登记一次；不取时钟。
    """
    return JobDefinition(
        DATA_ORIGIN_PREVIEW_TYPE,
        "预览改数据来源",
        DataOriginParameters,
        RecoveryMode.RESTART,
        partial(_execute, dependencies),
    )


def _execute(dependencies: NavWriteDependencies | None, context: ExecutionContext) -> None:
    """取作业提交人的身份快照与注入时钟，构造并保存预览；缺 worker 依赖属于缺陷。"""
    if (
        dependencies is None
        or not isinstance(context.parameters, DataOriginParameters)
        or context.mode not in (ExecutionMode.FRESH, ExecutionMode.RESTART)
    ):
        raise DefectError()
    parameters = context.parameters
    with session_scope(dependencies.rescan.engine, read_only=True) as session:
        actor = find_job(session, context.job_id).submitted_by
    stamp = ActorStamp(
        kind="人工标注",
        account_id=actor.account_id,
        account_name=actor.name,
        at=ensure_utc(context.clock.now()).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    def build(checkpoint: Callable[[], None]) -> PreviewBuild:
        return _build(dependencies, parameters, stamp, checkpoint)

    run_preview(context, dependencies, build)


def _build(
    dependencies: NavWriteDependencies,
    parameters: DataOriginParameters,
    stamp: ActorStamp,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """先记录 L12 状态，再读取该状态下的规范入口，报告与计划使用同一份新旧值。"""
    nav = dependencies.rescan.nav_root
    state = capture_preview_state(nav, (parameters.dataset_id,), None, checkpoint=checkpoint)
    canonical = tuple(item for item in state.datasets[0].entries if item.path.startswith("按任务/"))
    if len(canonical) != 1:
        raise nav_input_error(
            "NAV_DATA_ORIGIN",
            "必须有且只有唯一的按任务入口",
            objects=(("dataset_id", parameters.dataset_id),),
        )
    entry = canonical[0]
    location = EntryLocation(
        PurePosixPath(entry.path), View.TASK, None, None, PurePosixPath(entry.path).name
    )
    snapshot = read_entry(nav, location, checkpoint=checkpoint)
    if any(
        doc.payload is None
        or doc.payload.get("dataset_id") != parameters.dataset_id
        or ("dataset_name" in doc.payload and doc.payload["dataset_name"] != location.dataset_name)
        for doc in snapshot.documents
    ):
        raise nav_input_error(
            "NAV_DATA_ORIGIN",
            "基础 JSON 无法读取或身份不一致",
            objects=(("dataset_id", parameters.dataset_id), ("entry_path", entry.path)),
        )
    read = read_provenance(nav / location.path)
    before = FileImage(exists=False)
    old_origin = "未知"
    if read.state is ProvenanceState.ABSENT:
        document = new_provenance(
            parameters.dataset_id, location.dataset_name, parameters.data_origin, stamp
        )
        content = dump_navigation_json(dump_provenance(document))
    else:
        if read.document is None:
            raise nav_input_error(
                "NAV_DATA_ORIGIN",
                read.reason or "来源文件无法读取",
                objects=(("dataset_id", parameters.dataset_id),),
            )
        if (read.document.dataset_id, read.document.dataset_name) != (
            parameters.dataset_id,
            location.dataset_name,
        ):
            raise nav_input_error(
                "NAV_DATA_ORIGIN",
                "来源文件身份与规范入口不一致",
                objects=(("dataset_id", parameters.dataset_id), ("entry_path", entry.path)),
            )
        with _io.directory(nav / location.path) as descriptor:
            raw = _io.read_file(descriptor, "来源.json", checkpoint)
        if hashlib.sha256(raw).hexdigest() != read.sha256:
            raise nav_conflict_error("NAV_DATA_ORIGIN", "来源文件在预览读取期间变化")
        old_origin = read.document.data_origin
        document = with_data_origin(read.document, parameters.data_origin, stamp)
        content = _replace_origin(raw, dump_provenance(document))
        before = FileImage(exists=True, sha256=read.sha256, size_bytes=len(raw))
    relative = str(location.path / "来源.json")
    step = WriteFileStep(
        path=relative,
        before=before,
        after=FileImage(
            exists=True, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content)
        ),
        after_content=content.decode("utf-8"),
    )
    plan = NavWritePlan(
        operation=NavOperation.SET_DATA_ORIGIN,
        dataset_ids=(parameters.dataset_id,),
        steps=(step,),
        state=state,
    )
    report = PlanReport(
        file_count=len(plan.steps),
        link_count=0,
        directory_count=0,
        field_counts=(),
        listed_changes=(
            ListedChange(
                file=relative,
                json_path="data_origin",
                before=old_origin,
                after=document.data_origin,
            ),
        ),
        listed_total=1,
        checks=(
            CheckNote(
                name="导航层状态与来源格式",
                scope=CheckScope.FULL,
                detail="核对全部入口指纹；只改规范入口的来源文件",
            ),
        ),
        notices=(),
    )
    return PreviewBuild(plan, report, parameters.model_dump(mode="json"))


def _replace_origin(raw: bytes, payload: JsonObject) -> bytes:
    """仅替换两个顶层值；用标准库解码器定位值边界，避免模型补默认字段或重排血缘字节。"""
    text = raw.decode("utf-8")
    decoder = json.JSONDecoder()
    cursor = text.index("{") + 1
    replacements: list[tuple[int, int, str]] = []
    while True:
        while text[cursor].isspace() or text[cursor] == ",":
            cursor += 1
        if text[cursor] == "}":
            break
        key, cursor = decoder.raw_decode(text, cursor)
        while text[cursor].isspace() or text[cursor] == ":":
            cursor += 1
        start = cursor
        _, cursor = decoder.raw_decode(text, cursor)
        if key in ("data_origin", "data_origin_set_by"):
            value = json.dumps(payload[key], ensure_ascii=False, indent=2).replace("\n", "\n  ")
            replacements.append((start, cursor, value))
    # 从后往前替换，前面记录的字符偏移才不会失效；未触碰的血缘连空白和转义都原样保留。
    for start, end, value in reversed(replacements):
        text = text[:start] + value + text[end:]
    return text.encode("utf-8")
