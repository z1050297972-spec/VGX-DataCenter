"""M1.5-15 比对验收：通过两段扫描检查提示，所有文件均位于临时假导航层。"""

from pathlib import Path

from datasets_execution_support import dataset_case
from datasets_storage_support import enable_storage, scan
from datasets_support import edit_json
from nav_manifest import FakeNavigation

from rdp.jobs.datasets.types import PanelGroup, PanelSeverity


def test_robot_model_comparison(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """型号不同时只在规范入口提示，去首尾空白和大小写后相同则不提示。"""
    canonical = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    edit_json(
        fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/数据集信息.json",
        lambda data: data.update(robot_model="格式副本不参与比对"),
    )
    edit_json(
        fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json",
        lambda data: data.update(robot_type=" franka "),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        edit_json(canonical, lambda data: data.update(robot_model="PR2"))
        result = scan(case)
        owner, group = next(
            item
            for item in result.findings
            if item[1].diagnostics.rule == "INFO_ROBOT_MODEL_DIFFERS"
        )
        assert owner == "dataset:dataset-14"
        assert group.diagnostics.total == 1
        assert group.group is PanelGroup.DISK and group.severity is PanelSeverity.NOTICE
        sample = group.diagnostics.samples[0]
        assert sample.expected is not None
        assert "PR2" in sample.actual and "franka" in sample.expected
        assert sample.consequence and sample.next_step
        assert any(
            obj.key == "entry_path" and obj.value == "按任务/libero_10" for obj in sample.objects
        )
        assert result.warning_count == 0

        edit_json(canonical, lambda data: data.update(robot_model=" FRANKA "))
        assert not any(
            group.diagnostics.rule == "INFO_ROBOT_MODEL_DIFFERS" for _, group in scan(case).findings
        )


def test_fps_comparison(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """FPS 不同只在规范入口提示；原文件按现有半入规则取整后相同则不提示。"""
    canonical = fake_nav.nav_root / "按任务/libero_10/数据集信息.json"
    edit_json(
        fake_nav.nav_root / "按格式/lerobot/3.0/libero_10/数据集信息.json",
        lambda data: data.update(fps=60),
    )
    edit_json(
        fake_nav.storage_roots[0].path / "libero_v3/libero_10/meta/info.json",
        lambda data: data.update(fps=20.5),
    )
    with dataset_case(tmp_path / "state", fake_nav) as case:
        enable_storage(case)
        edit_json(canonical, lambda data: data.update(fps=30))
        result = scan(case)
        owner, group = next(
            item for item in result.findings if item[1].diagnostics.rule == "INFO_FPS_DIFFERS"
        )
        assert owner == "dataset:dataset-14"
        assert group.diagnostics.total == 1
        assert group.group is PanelGroup.DISK and group.severity is PanelSeverity.NOTICE
        sample = group.diagnostics.samples[0]
        assert sample.expected is not None
        assert "30" in sample.actual and "21" in sample.expected
        assert sample.consequence and sample.next_step
        assert any(
            obj.key == "entry_path" and obj.value == "按任务/libero_10" for obj in sample.objects
        )
        assert result.warning_count == 0

        edit_json(canonical, lambda data: data.update(fps=21))
        assert not any(
            group.diagnostics.rule == "INFO_FPS_DIFFERS" for _, group in scan(case).findings
        )
