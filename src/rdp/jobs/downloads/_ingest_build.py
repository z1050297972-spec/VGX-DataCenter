"""下载专用的创建计划适配（worker 领域层，M2-05）。

M1 的 build_dataset_preview 只接受已经存在的本地目标，不能检查尚未改名的正式位置，
且其公开契约拒绝 NAS。本入口用隔离检查得到的事实，复用它的 Planning、编号、
规范副本、格式副本和 provenance 构造规则；不改变 M1 的公开契约，也不重复实现写入。
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import cast

from rdp.jobs.datasets.types import JsonObject
from rdp.jobs.downloads._ingest_information import (
    download_lineage,
    filter_parameters,
    information_fields,
)
from rdp.jobs.downloads._ingest_receipt import Receipt
from rdp.jobs.downloads.ingest_models import IngestParameters
from rdp.jobs.navwrite import _ingest_creation as shared
from rdp.jobs.navwrite._create_read import Target
from rdp.jobs.navwrite.create_models import DatasetPreviewParameters, FirstLink
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.models import PreviewNotice
from rdp.jobs.navwrite.pipeline import NavWriteDependencies
from rdp.jobs.navwrite.provenance import ActorStamp


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
    """下载身份适配到共用 M1 计划；下载的筛选提示与血缘语义保持原样。"""
    receipt = observation.receipt
    metadata = cast(JsonObject, observation.files["metadata"])
    fields = information_fields(
        receipt, metadata, int(str(observation.files["size_bytes"])), observation.stamp
    )
    creation = DatasetPreviewParameters(
        dataset_name=parameters.dataset_name or "",
        data_origin="开源下载",
        link=FirstLink(name="原始数据", target_path=observation.target.path),
        format_entries=parameters.format_entries or (),
    )
    build = shared.build_creation(
        dependencies,
        creation,
        shared.CreationFacts(
            observation.target,
            fields,
            download_lineage(
                receipt, parameters.download_job_id, observation.stamp, *observation.times
            ),
            str(metadata["codebase_version"]),
            "下载成功、清单文件齐全且大小一致、LeRobot 元信息可读、同根目标不存在；不重算哈希、不做深度质检",
            source_output=False,
        ),
        checkpoint,
    )
    request = receipt.parameters
    if any((request.include, request.exclude, request.exclude_video, request.exclude_cameras)):
        build = replace(
            build,
            report=build.report.model_copy(
                update={
                    "notices": (
                        *build.report.notices,
                        PreviewNotice(
                            code="partial_download",
                            message="部分下载：排除了或筛选了 " + str(filter_parameters(receipt)),
                            objects=(),
                        ),
                    )
                }
            ),
        )
    return replace(
        build,
        parameters={
            "input": parameters.model_dump(mode="json"),
            "fields": cast(JsonObject, fields),
        },
    )
