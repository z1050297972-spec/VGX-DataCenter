"""M4.6 输入格式与空间默认值；使用临时导航层和数据库，不读取真实数据路径。"""

import tomllib
from pathlib import Path

import pytest
from datasets_execution_support import dataset_case
from nav_manifest import FakeNavigation
from tool_registry_support import tool_files

from rdp.infra.db.connection import session_scope
from rdp.jobs.conversion.parameters import InputSelection, selected_inputs, tool_parameters
from rdp.jobs.errors import JobInputError
from rdp.tools.manifest import ToolManifest


@pytest.mark.parametrize("explicit_ratio, expected", [(None, 130), (25, 25)])
def test_space_ratio_uses_manifest_only_when_omitted(
    tmp_path: Path, explicit_ratio: int | None, expected: int
) -> None:
    """清单默认 130 时，省略请求值取 130，显式填写旧默认 25 必须保留 25。"""
    files = tool_files(tmp_path)
    data = tomllib.loads((files.package / "tool.toml").read_text())
    data["runtime"]["space_ratio_percent"] = 130
    manifest = ToolManifest.model_validate(data)
    payload: dict[str, object] = {
        "dataset_id": "dataset-35",
        "source_ids": ["src_01e0bc7e9cc8"],
        "robot_model": "Galaxea R1 Lite",
    }
    if explicit_ratio is not None:
        payload["space_ratio_percent"] = explicit_ratio
    parameters = tool_parameters(manifest).model_validate(payload)
    assert parameters.space_ratio_percent == expected


@pytest.mark.parametrize("input_format", ["agibot_native", "mcap"])
@pytest.mark.parametrize(
    "source",
    [
        ("dataset-35", "src_01e0bc7e9cc8", "mcap"),
        ("dataset-31", "src_73acac5cbe70", "agibot_native"),
    ],
)
def test_selected_inputs_require_the_declared_format(
    tmp_path: Path,
    fake_nav: FakeNavigation,
    input_format: str,
    source: tuple[str, str, str],
) -> None:
    """格式按清单显式给定：MCAP 和 AgiBot 各自只接受匹配的数据块，错误诊断含目标格式。"""
    dataset_id, source_id, source_format = source
    selection = InputSelection(dataset_id=dataset_id, source_ids=[source_id], robot_model="model")
    with dataset_case(tmp_path / "state", fake_nav) as case:
        case.run()
        with session_scope(case.engine, read_only=True) as session:
            if input_format == source_format:
                paths = selected_inputs(session, selection, input_format=input_format)
                assert len(paths) == 1 and paths[0].is_relative_to(tmp_path)
            else:
                with pytest.raises(JobInputError) as error:
                    selected_inputs(session, selection, input_format=input_format)
                assert input_format in (error.value.diagnostics[0].expected or "")
