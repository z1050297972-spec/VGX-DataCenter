"""入库信息与血缘的纯数据构造（M2-05）；14 项和来源格式完全沿用 M1。

不解析已有 Markdown；只有结构化 meta/info.json 能证明的值才填入，未知值留空。
"""

import json
from typing import cast

from rdp.jobs.datasets.types import JsonObject, JsonValue
from rdp.jobs.downloads._ingest_receipt import Receipt
from rdp.jobs.navwrite.create_models import INFORMATION_FIELD_NAMES
from rdp.jobs.navwrite.provenance import ActorStamp, LineageRecord


def _text(value: JsonValue) -> str:
    """元数据缺值或 unknown 都留空，不补成看似已核验的值。"""
    if value is None or value == "unknown":
        return ""
    return str(value)


def _shape(value: JsonValue) -> str:
    """保留结构化 shape 的各个轴，不猜测动作单位和控制语义。"""
    if not isinstance(value, dict) or not isinstance(value.get("shape"), list):
        return ""
    return " x ".join(str(item) for item in cast(list[JsonValue], value["shape"]))


def information_fields(
    receipt: Receipt, metadata: JsonObject, size_bytes: int, stamp: ActorStamp
) -> dict[str, str]:
    """从下载回执和格式元信息填 14 项，顺序来自唯一的 M1 名称表。"""
    result = metadata_fields(metadata, size_bytes)
    request = receipt.parameters
    result.update(
        {
            "数据集标识": request.repo_id,
            "地址": f"https://hf-mirror.com/datasets/{request.repo_id}/tree/{receipt.commit}",
            "信息来源与核验日期": f"hf-mirror 下载，{request.repo_id}@{receipt.commit}，{stamp.at[:10]}",
        }
    )
    return result


def metadata_fields(metadata: JsonObject, size_bytes: int) -> dict[str, str]:
    """从格式元信息填充可证明的字段，来源身份留给下载或转换调用方。"""
    result: dict[str, str] = dict.fromkeys(INFORMATION_FIELD_NAMES, "")
    features = metadata.get("features")
    features = features if isinstance(features, dict) else {}
    cameras = [
        f"{key}: {_shape(value)}"
        for key, value in features.items()
        if isinstance(value, dict) and value.get("dtype") == "video"
    ]
    result.update(
        {
            "数据大小": f"{size_bytes} bytes",
            "采集机器人型号": _text(metadata.get("robot_type")),
            "数据格式": _text(metadata.get("codebase_version")),
            "FPS": _text(metadata.get("fps")),
            "相机配置": "\n".join(cameras),
            "状态维度": _shape(features.get("observation.state")),
            "动作维度": _shape(features.get("action")),
        }
    )
    episodes, frames = metadata.get("total_episodes"), metadata.get("total_frames")
    if episodes is not None and frames is not None:
        result[INFORMATION_FIELD_NAMES[12]] = f"{episodes} episodes / {frames} frames"
    return result


def filter_parameters(receipt: Receipt) -> dict[str, str | int | float | bool | None]:
    """来源参数不能嵌套列表，列表按 JSON 文本保存在现有 parameters 扩展字典里。"""
    p = receipt.parameters
    return {
        "repo_type": p.repo_type,
        "repo_id": p.repo_id,
        "commit": receipt.commit,
        "endpoint": "https://hf-mirror.com",
        "include": json.dumps(p.include, ensure_ascii=False),
        "exclude": json.dumps(p.exclude, ensure_ascii=False),
        "exclude_video": p.exclude_video,
        "exclude_cameras": json.dumps(p.exclude_cameras, ensure_ascii=False),
    }


def download_lineage(
    receipt: Receipt,
    download_job_id: int,
    stamp: ActorStamp,
    started_at: str | None,
    finished_at: str | None,
) -> LineageRecord:
    """下载时间来自作业记录；入库作业编号在确认执行时补入同一份计划的血缘记录。"""
    return LineageRecord(
        record_id=1,
        kind="下载",
        status="完整",
        note="已检查下载清单大小与 LeRobot 元信息；未做深度质检",
        inputs=(),
        outputs=({"codebase_version": None},),
        tool=None,
        config=None,
        robot_profile=None,
        parameters={
            **filter_parameters(receipt),
            "download_job_id": download_job_id,
            "ingest_job_id": None,
            "download_started_at": started_at,
            "download_finished_at": finished_at,
        },
        job_id=None,
        started_at=started_at,
        finished_at=finished_at,
        ingest_check={"checked_at": stamp.at, "result": "文件齐全且大小匹配"},
        recorded_by=stamp,
    )
