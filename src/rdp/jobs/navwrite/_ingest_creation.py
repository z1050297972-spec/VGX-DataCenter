"""暂存入库共用的 M1 创建计划适配；只接收 worker 已验证的目标事实。

复用 Planning、编号分配、导航快照与副本规则；尚未改名的目标不能走只接受现存目标的公开读取入口。
下载和转换各自提供身份、14项与血缘，本模块不读取存储、不移动目录。
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import PurePosixPath
from typing import cast

from rdp.jobs.datasets.types import EntryLocation, JsonObject, View
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite._create_read import Target
from rdp.jobs.navwrite.allocation import allocate_dataset_id
from rdp.jobs.navwrite.create_models import DatasetPreviewParameters
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.jsonio import dump_navigation_json, regenerate_derived_fields
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    NavOperation,
    NavPreview,
    NavWritePlan,
    Step,
    WriteFileStep,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.navwrite.provenance import (
    LineageRecord,
    dump_provenance,
    new_provenance,
    with_lineage_record,
)


@dataclass(frozen=True)
class CreationFacts:
    """两类入库共同需要的已验证目标、信息与追加血缘。

    Attributes:
        target: 尚未改名的正式位置及已验证格式。
        fields: 按M1名称表填好的14项正文。
        lineage: 来自实际生产作业的追加血缘。
        codebase_version: 产物声明的完整版本字符串。
        check_detail: 本次入库检查的摘要。
        source_output: 转换写数据块编号；False保留既有下载的输出数据集编号契约。
    """

    target: Target
    fields: dict[str, str]
    lineage: LineageRecord
    codebase_version: str
    check_detail: str
    source_output: bool = True


def build_creation(
    dependencies: NavWriteDependencies,
    parameters: DatasetPreviewParameters,
    observation: CreationFacts,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """以 M1 唯一规则创建按任务入口、格式副本和血缘，不预先移动数据。"""
    target = observation.target
    name = parameters.dataset_name or ""
    location = EntryLocation(PurePosixPath("按任务", name), View.TASK, None, None, name)
    nav = dependencies.rescan.nav_root
    if (nav / location.path).exists() or (nav / location.path).is_symlink():
        raise nav_input_error("DOWNLOAD_INGEST", "按任务下数据集名称已被占用")
    state = capture_preview_state(nav, (), str(location.path), checkpoint=checkpoint)
    canonical = plans.new_snapshot(location, allocate_dataset_id(nav), parameters.information)
    selected = plans.format_locations(name, parameters.format_entries or ())
    fields = observation.fields
    information = plans.payload(canonical, 1)
    information["data_origin"] = parameters.data_origin
    for field in cast(list[JsonObject], information["fields"]):
        field["value_markdown"] = fields[str(field["name"])]
    link = parameters.link
    if link is None:
        raise nav_input_error("INGEST", "入库必须提供首条链接")
    planning = plans.Planning(nav, canonical)
    planning.ensure_directory(location.path)
    manifest = plans.payload(canonical, 0)
    planning.link(location, link, target, manifest)
    planning.extend_manifest(manifest, target)
    canonical = plans.with_documents(
        canonical,
        (
            dump_navigation_json(regenerate_derived_fields(manifest, location)),
            dump_navigation_json(information),
            dump_navigation_json(plans.payload(canonical, 2)),
        ),
    )
    for index, document in enumerate(canonical.documents):
        planning.write(
            str(location.path / document.name),
            None,
            dump_navigation_json(plans.payload(canonical, index)),
        )
    provenance = with_lineage_record(
        new_provenance(canonical.dataset_id or "", name),
        observation.lineage.model_copy(
            update={
                "outputs": (
                    {
                        "source_id": str(
                            cast(list[JsonObject], manifest["sources"])[0]["source_id"]
                        ),
                        "format": target.format,
                        "codebase_version": observation.codebase_version,
                    }
                    if observation.source_output
                    else {
                        "dataset_id": canonical.dataset_id,
                        "codebase_version": observation.codebase_version,
                    },
                )
            }
        ),
    )
    planning.write(
        str(location.path / "来源.json"), None, dump_navigation_json(dump_provenance(provenance))
    )
    formats = planning.replicas(canonical, (), selected, link, target)
    verify_preview_state(nav, state, checkpoint=checkpoint)
    plan = NavWritePlan(
        operation=NavOperation.CREATE_DATASET,
        dataset_ids=(canonical.dataset_id or "",),
        steps=tuple(planning.steps),
        state=state,
    )
    report = planning.report(plan, target, selected, formats)
    report = report.model_copy(
        update={
            "checks": (
                *report.checks,
                CheckNote(
                    name="入库检查",
                    scope=CheckScope.FULL,
                    detail=observation.check_detail,
                ),
            )
        }
    )
    return PreviewBuild(
        plan,
        report,
        {"input": parameters.model_dump(mode="json"), "fields": cast(JsonObject, fields)},
    )


def with_ingest_date(preview: NavPreview, now: datetime) -> NavPreview:
    """仅刷新14项的实际入库日期，已确认的名称、路径、原作业时间保持不变。"""
    steps: list[Step] = []
    for step in preview.plan.steps:
        if step.op == "write_file" and step.path.endswith("/数据集信息.json"):
            payload = cast(JsonObject, json.loads(step.after_content))
            for field in cast(list[JsonObject], payload["fields"]):
                if field["name"] == "信息来源与核验日期":
                    prefix = str(field["value_markdown"]).rsplit("，", 1)[0]
                    field["value_markdown"] = f"{prefix}，{now.date().isoformat()}"
            content = dump_navigation_json(payload)
            step = WriteFileStep(
                path=step.path,
                before=step.before,
                after=plans.image(content),
                after_content=content.decode(),
            )
        steps.append(step)
    return preview.model_copy(
        update={"plan": preview.plan.model_copy(update={"steps": tuple(steps)})}
    )
