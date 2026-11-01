"""下载专用的创建计划适配（worker 领域层，M2-05）。

M1 的 build_dataset_preview 只接受已经存在的本地目标，不能检查尚未改名的正式位置，
且其公开契约拒绝 NAS。本入口用隔离检查得到的事实，复用它的 Planning、编号、
规范副本、格式副本和 provenance 构造规则；不改变 M1 的公开契约，也不重复实现写入。
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import cast

from rdp.jobs.datasets.types import EntryLocation, JsonObject, View
from rdp.jobs.downloads._ingest_information import (
    download_lineage,
    filter_parameters,
    information_fields,
)
from rdp.jobs.downloads._ingest_receipt import Receipt
from rdp.jobs.downloads.ingest_models import IngestParameters
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite._create_read import Target
from rdp.jobs.navwrite.allocation import allocate_dataset_id
from rdp.jobs.navwrite.create_models import FirstLink
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.jsonio import dump_navigation_json, regenerate_derived_fields
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    NavOperation,
    NavWritePlan,
    PreviewNotice,
)
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.navwrite.provenance import (
    ActorStamp,
    dump_provenance,
    new_provenance,
    with_lineage_record,
)


@dataclass(frozen=True)
class CreationFacts:
    """已验证的入库事实，供同一份预览计划使用。

    Attributes:
        receipt: 固定下载清单与 commit。
        files: 检查子进程返回的元信息、总字节数及目录身份。
        target: 正式位置和读取的格式版本。
        stamp: 预览提交人的 UTC 印记。
        times: 下载作业的 UTC 起止时间文本，旧记录缺失时为 None。
    """

    receipt: Receipt
    files: JsonObject
    target: Target
    stamp: ActorStamp
    times: tuple[str | None, str | None]


def build_creation(
    dependencies: NavWriteDependencies,
    parameters: IngestParameters,
    observation: CreationFacts,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """按 M1 的单一创建规则组装正式路径的计划；存储已检查，预览不预先移动目录。"""
    receipt, facts, target, stamp, times = (
        observation.receipt,
        observation.files,
        observation.target,
        observation.stamp,
        observation.times,
    )
    name = parameters.dataset_name or ""
    location = EntryLocation(PurePosixPath("按任务", name), View.TASK, None, None, name)
    nav = dependencies.rescan.nav_root
    if (nav / location.path).exists() or (nav / location.path).is_symlink():
        raise nav_input_error("DOWNLOAD_INGEST", "按任务下数据集名称已被占用")
    state = capture_preview_state(nav, (), str(location.path), checkpoint=checkpoint)
    canonical = plans.new_snapshot(location, allocate_dataset_id(nav))
    selected = plans.format_locations(name, parameters.format_entries or ())
    metadata = cast(JsonObject, facts["metadata"])
    fields = information_fields(receipt, metadata, int(str(facts["size_bytes"])), stamp)
    information = plans.payload(canonical, 1)
    for field in cast(list[JsonObject], information["fields"]):
        field["value_markdown"] = fields[str(field["name"])]
    link = FirstLink(name="原始数据", target_path=target.path)
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
        new_provenance(canonical.dataset_id or "", name, "开源下载", stamp),
        download_lineage(receipt, parameters.download_job_id, stamp, *times).model_copy(
            update={
                "outputs": (
                    {
                        "dataset_id": canonical.dataset_id,
                        "codebase_version": str(metadata["codebase_version"]),
                    },
                )
            }
        ),
    )
    planning.write(
        str(location.path / "来源.json"), None, dump_navigation_json(dump_provenance(provenance))
    )
    formats = planning.replicas(canonical, (), selected, link, target)
    if any(
        (
            receipt.parameters.include,
            receipt.parameters.exclude,
            receipt.parameters.exclude_video,
            receipt.parameters.exclude_cameras,
        )
    ):
        planning.notices.append(
            PreviewNotice(
                code="partial_download",
                message="部分下载：排除了或筛选了 " + str(filter_parameters(receipt)),
                objects=(),
            )
        )
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
                    detail="下载成功、清单文件齐全且大小一致、LeRobot 元信息可读、同根目标不存在；不重算哈希、不做深度质检",
                ),
            )
        }
    )
    return PreviewBuild(
        plan,
        report,
        {"input": parameters.model_dump(mode="json"), "fields": cast(JsonObject, fields)},
    )
