"""入库检查值契约（领域层，M4-04）；只描述四层结论，不访问存储或决定入库。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from rdp.infra.diagnostics import Diagnostic

type CheckResult = Literal["通过", "有警告", "不通过"]


class CheckLayer(BaseModel):
    """一层检查的结论；前置层失败时，后续层明确记为未检查。"""

    name: Literal["结构", "计数", "视频", "内容"]
    result: Literal["通过", "有警告", "不通过", "未检查"]
    diagnostics: tuple[Diagnostic, ...] = ()


class CheckReport(BaseModel):
    """同一次检查的四层结果；warning_count为报告中警告诊断的数量。"""

    result: CheckResult
    warning_count: int = 0
    layers: tuple[CheckLayer, ...]


class FeatureInfo(BaseModel):
    """只解释检查需要的特征声明，保留工具自带的其他信息。"""

    dtype: str
    shape: tuple[int, ...]
    info: dict[str, JsonValue] = {}


class LeRobotInfo(BaseModel):
    """v2.1/v3.0 共用的顶层字段；额外字段仅警告，不丢弃原文。"""

    model_config = ConfigDict(extra="allow")
    codebase_version: Literal["v2.1", "v3.0"]
    fps: float = Field(gt=0, allow_inf_nan=False)
    total_episodes: int = Field(strict=True, gt=0)
    total_frames: int = Field(strict=True, gt=0)
    features: dict[str, FeatureInfo]
    total_tasks: int | None = None
    chunks_size: int = Field(default=1000, gt=0)
    data_files_size_in_mb: int | None = None
    video_files_size_in_mb: int | None = None
    data_path: str
    video_path: str | None = None
    robot_type: str | None = None
    splits: dict[str, str] = {}
    total_chunks: int | None = None
    total_videos: int | None = None


class IngestCheckResult(BaseModel):
    """作业结果内的检查快照；自动就绪仅在默认名、位置空闲且全通过时为真。"""

    conversion_job_id: int
    report: CheckReport
    size_bytes: int | None = None
    automatic_ready: bool = False
