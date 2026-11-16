"""视频元数据兼容回归：临时 LeRobot v3 产物经四层检查，仅替换 ffprobe 进程边界。"""

import json
import subprocess
from importlib import import_module
from pathlib import Path
from typing import Any

import pytest

from rdp.jobs.conversion._check_child import check
from rdp.jobs.conversion.check_models import FeatureInfo


def _product(root: Path, feature: dict[str, Any]) -> Path:
    """两帧一集的完整最小 v3 产物；视频内容由 ffprobe 边界替身描述。"""
    arrow = import_module("pyarrow")
    parquet = import_module("pyarrow.parquet")
    (root / "meta/episodes/chunk-000").mkdir(parents=True)
    (root / "data/chunk-000").mkdir(parents=True)
    video = root / "videos/observation.images.camera/chunk-000/file-000.mkv"
    video.parent.mkdir(parents=True)
    video.write_bytes(b"ffprobe boundary fixture")
    (root / "meta/info.json").write_text(
        json.dumps(
            {
                "codebase_version": "v3.0",
                "fps": 2,
                "total_episodes": 1,
                "total_frames": 2,
                "data_path": "data/chunk-{chunk_index:03d}/file-{file_index:03d}.parquet",
                "video_path": "videos/{video_key}/chunk-{chunk_index:03d}/file-{file_index:03d}.mkv",
                "features": {
                    "observation.state": {"dtype": "float32", "shape": [1]},
                    "action": {"dtype": "float32", "shape": [1]},
                    "observation.images.camera": feature,
                },
            }
        )
    )
    (root / "meta/stats.json").write_text("{}")
    parquet.write_table(
        arrow.table({"task_index": [0], "task": ["测试"]}), root / "meta/tasks.parquet"
    )
    parquet.write_table(
        arrow.Table.from_pylist(
            [
                {
                    "episode_index": 0,
                    "length": 2,
                    "data/chunk_index": 0,
                    "data/file_index": 0,
                    "videos/observation.images.camera/chunk_index": 0,
                    "videos/observation.images.camera/file_index": 0,
                }
            ]
        ),
        root / "meta/episodes/chunk-000/file-000.parquet",
    )
    parquet.write_table(
        arrow.table(
            {
                "episode_index": [0, 0],
                "observation.state": [[0.0], [1.0]],
                "action": [[0.0], [1.0]],
            }
        ),
        root / "data/chunk-000/file-000.parquet",
    )
    return root


def _ffprobe(
    monkeypatch: pytest.MonkeyPatch,
    codec: str,
    *,
    width: int = 32,
    duration: float = 1.0,
) -> None:
    """保留真实元数据解析和四层编排，只替换外部探测器返回的编码、尺寸、秒数。"""

    def run(argv: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert Path(argv[0]).name == "ffprobe"
        assert Path(argv[-1]).is_file()
        payload = {
            "streams": [
                {"codec_name": codec, "width": width, "height": 16, "duration": str(duration)}
            ],
            "format": {"duration": str(duration)},
        }
        return subprocess.CompletedProcess(argv, 0, json.dumps(payload).encode(), b"")

    monkeypatch.setattr(subprocess, "run", run)


@pytest.mark.parametrize("declared, actual", [("png", "png"), ("libdav1d", "av1")])
def test_legacy_video_info_passes_all_layers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    declared: str,
    actual: str,
) -> None:
    """合法旧 video_info 中 PNG/AV1 编码被读取并核对，完整 v3 产物四层都通过。"""
    root = _product(
        tmp_path / "out",
        {
            "dtype": "video",
            "shape": [16, 32, 1 if declared == "png" else 3],
            "video_info": {"video.codec": declared, "video.width": 32, "video.height": 16},
            "names": ["height", "width", "channels"],
            "vendor_extension": {"depth": declared == "png"},
        },
    )
    _ffprobe(monkeypatch, actual)
    original = (root / "meta/info.json").read_bytes()
    report = check(root, "v3.0", tmp_path)
    assert [layer.result for layer in report.layers] == ["通过"] * 4
    assert report.warning_count == 0
    assert (root / "meta/info.json").read_bytes() == original


@pytest.mark.parametrize(
    "legacy",
    [
        {"video.codec": "av1"},
        {"video.codec": "h264", "video.width": 64},
        None,
        [],
    ],
)
def test_dual_video_metadata_conflicts_or_invalid_legacy_are_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    legacy: object,
) -> None:
    """两份声明冲突或旧字段形状不合法时在结构层拒绝，不能因 info 可用就忽略旧字段。"""
    root = _product(
        tmp_path / "out",
        {
            "dtype": "video",
            "shape": [16, 32, 3],
            "info": {"video.codec": "h264", "video.width": 32},
            "video_info": legacy,
        },
    )
    _ffprobe(monkeypatch, "h264")
    report = check(root, "v3.0", tmp_path)
    assert [layer.result for layer in report.layers] == ["不通过", "未检查", "未检查", "未检查"]


@pytest.mark.parametrize("field", ["info", "video_info"])
@pytest.mark.parametrize(
    "observation",
    [
        ("png", "av1", 32, 1.0),
        ("libdav1d", "h264", 32, 1.0),
        ("libunknown", "unknown", 32, 1.0),
        ("libdav1d", "av1", 64, 1.0),
        ("libdav1d", "av1", 32, 2.0),
    ],
)
def test_video_compatibility_preserves_codec_size_and_duration_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    observation: tuple[str, str, int, float],
) -> None:
    """新旧字段均严格拒绝不同编码、未知 lib 前缀别名、错误尺寸和超过一帧的时长差。"""
    declared, actual, width, duration = observation
    root = _product(
        tmp_path / "out",
        {
            "dtype": "video",
            "shape": [16, 32, 3],
            field: {"video.codec": declared},
        },
    )
    _ffprobe(monkeypatch, actual, width=width, duration=duration)
    report = check(root, "v3.0", tmp_path)
    assert [layer.result for layer in report.layers] == ["通过", "通过", "不通过", "未检查"]
    assert report.layers[2].diagnostics[0].rule == "conversion.check.video"


@pytest.mark.parametrize(
    "current, legacy",
    [
        ({"video.codec": "h264"}, None),
        ({"video.codec": "h264"}, {"video.codec": "h264", "video.width": 32}),
        ({"video.codec": "h264"}, {"video.width": 32}),
        ({"video.width": 32}, {"video.codec": "h264"}),
    ],
)
def test_current_info_and_consistent_dual_fields_pass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    current: dict[str, Any],
    legacy: dict[str, Any] | None,
) -> None:
    """当前 MCAP info 形状不变；新旧字段的相同键一致、互补键合并时仍通过。"""
    feature: dict[str, Any] = {
        "dtype": "video",
        "shape": [16, 32, 3],
        "info": current,
        "names": ["height", "width", "channels"],
        "vendor_extension": "retained",
    }
    if legacy is not None:
        feature["video_info"] = legacy
    root = _product(tmp_path / "out", feature)
    _ffprobe(monkeypatch, "h264")
    report = check(root, "v3.0", tmp_path)
    assert [layer.result for layer in report.layers] == ["通过"] * 4


def test_feature_normalization_preserves_extra_fields() -> None:
    """旧别名进入规范 info，额外 feature 字段保留在内存序列化结果，不生成两份声明。"""
    feature = FeatureInfo.model_validate_json(
        json.dumps(
            {
                "dtype": "video",
                "shape": [16, 32, 1],
                "video_info": {"video.codec": "png"},
                "names": ["height", "width", "channels"],
                "vendor_extension": {"depth": True},
            }
        )
    )
    assert feature.model_dump(mode="json") == {
        "dtype": "video",
        "shape": [16, 32, 1],
        "info": {"video.codec": "png"},
        "names": ["height", "width", "channels"],
        "vendor_extension": {"depth": True},
    }
