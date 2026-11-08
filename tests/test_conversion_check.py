"""M4-04 四层入库检查的关键拒绝行为；检查边界独立于作业与导航写入。"""

from pathlib import Path

import pytest
from conversion_ingest_support import product

from rdp.jobs.conversion.check import check_output


def test_missing_info_fails_structure(tmp_path: Path) -> None:
    """验收1：缺 meta/info.json 给结构不通过，保留产物。"""
    output = product(tmp_path / "out")
    (output / "meta/info.json").unlink()
    result = check_output(output, "v3.0")
    assert result.result == "不通过"
    assert result.layers[0].name == "结构"
    assert result.layers[0].result == "不通过"
    assert result.layers[0].diagnostics
    assert output.is_dir()


def test_output_version_mismatch_fails_structure(tmp_path: Path) -> None:
    """验收1：产物codebase_version与转换参数output_format不符时，结构层拒绝。"""
    output = product(tmp_path / "out")
    # 产物保持完整有效的v3.0布局，只有转换参数要求v2.1，避免因文件缺失而失败。
    result = check_output(output, "v2.1")
    assert result.result == "不通过"
    assert [layer.result for layer in result.layers] == ["不通过", "未检查", "未检查", "未检查"]


def test_wrong_frame_count_fails_counts(tmp_path: Path) -> None:
    """验收1：声明帧数与真实 parquet 行数不等时，计数层拒绝。"""
    import json

    output = product(tmp_path / "out")
    path = output / "meta/info.json"
    info = json.loads(path.read_text())
    info["total_frames"] = 1648
    path.write_text(json.dumps(info))
    result = check_output(output, "v3.0")
    assert result.result == "不通过"
    assert result.layers[0].result == "通过"
    assert result.layers[1].result == "不通过"


def test_missing_video_fails_video_layer(tmp_path: Path) -> None:
    """验收1：元数据引用的视频缺失时，视频层拒绝且不做内容检查。"""
    output = product(tmp_path / "out")
    next(output.glob("videos/*/chunk-*/*.mp4")).unlink()
    result = check_output(output, "v3.0")
    assert result.layers[1].result == "通过"
    assert result.layers[2].result == "不通过"
    assert result.layers[3].result == "未检查"


def test_wrong_video_resolution_fails_video_layer(tmp_path: Path) -> None:
    """验收1：视频存在但分辨率与info声明不符时，视频层拒绝且不检查内容。"""
    import json

    output = product(tmp_path / "out")
    path = output / "meta/info.json"
    info = json.loads(path.read_text())
    # 实际视频为宽32、高16；只改声明尺寸，其余数据保持有效以隔离视频层行为。
    for feature in info["features"].values():
        if feature["dtype"] == "video":
            feature["shape"] = [16, 64, 3]
            feature["info"]["video.width"] = 64
    path.write_text(json.dumps(info))
    result = check_output(output, "v3.0")
    assert result.result == "不通过"
    assert [layer.result for layer in result.layers] == ["通过", "通过", "不通过", "未检查"]


def test_nan_in_middle_episode_fails_content(tmp_path: Path) -> None:
    """验收1：中间episode的state有NaN时内容层拒绝，前三层通过。"""
    output = product(tmp_path / "out", nan=True)
    result = check_output(output, "v3.0")
    assert [layer.result for layer in result.layers] == ["通过", "通过", "通过", "不通过"]
    assert result.result == "不通过"


@pytest.mark.parametrize("version", ["v3.0", "v2.1"])
def test_valid_layout_passes_all_layers(tmp_path: Path, version: str) -> None:
    """验收2的检查前提：v3共享文件和v2逐episode布局均能通过四层检查。"""
    from conversion_ingest_support import version_two

    output = product(tmp_path / "out")
    if version == "v2.1":
        version_two(output)
    result = check_output(output, version)
    assert result.result == "通过"
    assert result.warning_count == 0
    assert [layer.result for layer in result.layers] == ["通过"] * 4


def test_extra_info_field_requires_confirmation(tmp_path: Path) -> None:
    """验收3的检查前提：未知info顶层字段只产生警告，四层仍完成。"""
    import json

    output = product(tmp_path / "out")
    path = output / "meta/info.json"
    info = json.loads(path.read_text())
    info["vendor_extension"] = "future"
    path.write_text(json.dumps(info))
    result = check_output(output, "v3.0")
    assert result.result == "有警告"
    assert result.warning_count == 1
    assert result.layers[0].diagnostics[0].actual == "未知info顶层字段：vendor_extension"
    assert [layer.result for layer in result.layers[1:]] == ["通过"] * 3
