"""转换身份适配到共用 M1 创建计划；血缘只使用实际转换回执和原作业时间。"""

import json
from collections.abc import Callable
from dataclasses import replace
from typing import cast

from rdp.jobs.conversion._ingest_read import Conversion
from rdp.jobs.conversion.check_models import CheckReport
from rdp.jobs.conversion.ingest_models import ConversionIngestParameters
from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_access import access
from rdp.jobs.downloads._ingest_information import metadata_fields
from rdp.jobs.downloads.plan import _target_parts  # pyright: ignore[reportPrivateUsage] # 理由：工单要求沿用M2同根目标路径规则。
from rdp.jobs.navwrite import _ingest_creation as shared
from rdp.jobs.navwrite._create_read import Target
from rdp.jobs.navwrite.create_models import (
    DatasetInformation,
    DatasetPreviewParameters,
    FirstLink,
    FormatEntrySelection,
)
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.provenance import ActorStamp, LineageRecord


def lineage(value: Conversion, facts: JsonObject, stamp: ActorStamp) -> LineageRecord:
    """完整配置与工具指纹取实际回执；列表参数沿用M2的JSON文本编码。"""
    receipt = cast(JsonObject, facts["receipt"])
    tool = cast(JsonObject, receipt["tool"])
    config = cast(JsonObject, receipt["configuration"])
    report = CheckReport.model_validate(facts["report"])
    record = value.record
    return LineageRecord(
        record_id=1,
        kind="转换",
        status="完整",
        note=None,
        inputs=tuple(
            {"dataset_id": str(item["dataset_id"]), "source_id": str(item["source_id"])}
            for item in cast(list[JsonObject], receipt["inputs"])
        ),
        outputs=(),
        tool={
            key: cast(str | None, tool.get(source))
            for key, source in (
                ("name", "name"),
                ("version", "version"),
                ("commit", "source_commit"),
                ("binary_sha256", "binary_sha256"),
            )
        },
        config={
            "path": str(config["filename"]),
            "sha256": str(config["sha256"]),
            "text": str(config["content"]),
        },
        robot_profile=None,
        parameters={
            key: json.dumps(item, ensure_ascii=False)
            if isinstance(item, (list, dict))
            else cast(str | int | float | bool | None, item)
            for key, item in record.parameters.items()
        },
        job_id=record.job_id,
        started_at=record.started_at.strftime("%Y-%m-%dT%H:%M:%SZ") if record.started_at else None,
        finished_at=record.ended_at.strftime("%Y-%m-%dT%H:%M:%SZ") if record.ended_at else None,
        ingest_check={"result": report.result, "warning_count": report.warning_count},
        recorded_by=stamp,
    )


def build(
    deps: NavWriteDependencies,
    parameters: ConversionIngestParameters,
    value: Conversion,
    facts: JsonObject,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """只组装已检查事实的创建计划；默认名碰撞时加转换编号供人工选择。"""
    metadata = cast(JsonObject, facts["metadata"])
    version = str(metadata["codebase_version"]).removeprefix("v")
    name = parameters.dataset_name or value.input_name.removesuffix("_mcap") + "_lerobot"
    entry = deps.rescan.nav_root / "按任务" / name
    occupied = entry.exists() or entry.is_symlink()
    if occupied and parameters.dataset_name is None:
        name += f"_{value.record.job_id}"
    target = parameters.target_subdir or f"转换/{name}"
    parts = _target_parts(target)
    if parts[0] == "暂存":
        raise nav_input_error("CONVERSION_INGEST", "正式位置必须在暂存之外")
    normalized = parameters.model_copy(
        update={
            "dataset_name": name,
            "target_subdir": "/".join(parts),
            "format_entries": parameters.format_entries
            if parameters.format_entries is not None
            else (FormatEntrySelection(format="lerobot", version=version),),
        }
    )
    probe = access(
        "probe", value.root, f"暂存/转换/{value.record.job_id}/out", target, deps.paths.root
    )
    if probe["target_exists"]:
        if parameters.target_subdir is not None:
            raise nav_input_error("CONVERSION_INGEST", "正式位置已被占用")
        occupied = True
        normalized = normalized.model_copy(
            update={"target_subdir": target + f"_{value.record.job_id}"}
        )
    result = _creation(deps, normalized, value, facts, checkpoint)
    return replace(result, parameters={**result.parameters, "default_occupied": occupied})


def _creation(
    deps: NavWriteDependencies,
    parameters: ConversionIngestParameters,
    value: Conversion,
    facts: JsonObject,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """来源与分类沿用输入规范JSON，帧率取产物；collection不传，由M1保持缺键。"""
    stamp = ActorStamp(
        kind="worker", account_id=None, account_name=None, at=str(facts["checked_at"])
    )
    metadata = cast(JsonObject, facts["metadata"])
    name, target = parameters.dataset_name or "", parameters.target_subdir or ""
    # 导航为本机受控文件；存储根读取已在隔离进程完成。
    information = json.loads(
        (deps.rescan.nav_root / value.input_entry / "数据集信息.json").read_text()
    )
    creation = DatasetPreviewParameters(
        dataset_name=name,
        data_origin=information.get("data_origin", "未知"),
        # 转换不改变采集分类，但帧率可能重采样，必须取产物声明而非输入数据集。
        information=DatasetInformation(
            robot_model=information.get("robot_model", ""),
            scene=information.get("scene", ()),
            tasks=information.get("tasks", ()),
            fps=cast(int, metadata["fps"]),
        ),
        link=FirstLink(name="原始数据", target_path=str(value.root.path / target)),
        format_entries=parameters.format_entries or (),
    )
    fields = metadata_fields(metadata, int(str(facts["size_bytes"])))
    fields.update(
        {
            "数据集标识": name,
            "地址": str(value.root.path / target),
            "信息来源与核验日期": f"mcap2lerobot 转换自 {value.input_name}，转换作业 {value.record.job_id}，{stamp.at[:10]}",
        }
    )
    result = shared.build_creation(
        deps,
        creation,
        shared.CreationFacts(
            Target(
                str(value.root.path / target),
                "directory",
                "lerobot",
                str(metadata["codebase_version"]).removeprefix("v"),
                "meta_info",
            ),
            fields,
            lineage(value, facts, stamp),
            str(metadata["codebase_version"]),
            "LeRobot 四层入库检查完成",
        ),
        checkpoint,
    )
    return replace(
        result,
        parameters={
            "input": parameters.model_dump(mode="json"),
            "fields": cast(JsonObject, fields),
            "check": facts["report"],
            "move": {
                "storage_root": value.root.name,
                "stage": f"暂存/转换/{value.record.job_id}/out",
                "target": target,
                "dev": facts["dev"],
                "ino": facts["ino"],
            },
        },
    )
