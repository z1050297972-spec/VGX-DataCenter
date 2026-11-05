"""M1.5-03 场景、任务词表与分类筛选：词表、读取、索引、提示、筛选、候选与场景树。

期望值取自词表初稿（vocab-draft.md）和手写的小样本，不调用被测逻辑生成。
"""

import json
from pathlib import Path
from typing import Any

import pytest
from dataset_api_support import browser_case
from datasets_support import checkpoint, location
from nav_manifest import FakeNavigation

from rdp.jobs.datasets import vocabulary
from rdp.jobs.datasets.reading import read_entry

SCENE_CODES = (
    "kitchen",
    "home_living",
    "tabletop",
    "office",
    "retail",
    "logistics",
    "industrial",
    "public_space",
    "mixed",
    "unknown",
)
TASK_CODES = (
    "pick_place",
    "articulated",
    "fold",
    "wipe_clean",
    "tidy",
    "cook",
    "mobile_nav",
    "tool_use",
    "bimanual",
    "human_demo",
    "long_horizon",
    "unknown",
)


def label(
    nav: FakeNavigation,
    name: str,
    *,
    scene: Any = None,
    tasks: Any = None,
    robot_model: Any = None,
) -> None:
    """只改按任务规范副本的 数据集信息.json 顶层三个字段；None 表示不写该键。"""
    path = nav.nav_root / "按任务" / name / "数据集信息.json"
    data = json.loads(path.read_text())
    for key, value in (("scene", scene), ("tasks", tasks), ("robot_model", robot_model)):
        if value is not None:
            data[key] = value
    path.write_text(json.dumps(data, ensure_ascii=False))


def test_vocabulary_matches_approved_draft() -> None:
    """契约：场景 10 个、任务 12 个，编码顺序与中文名称同 vocab-draft.md；编码唯一。"""
    assert tuple(item.code for item in vocabulary.SCENES) == SCENE_CODES
    assert tuple(item.code for item in vocabulary.TASKS) == TASK_CODES
    assert vocabulary.scene_name("kitchen") == "家居-厨房"
    assert vocabulary.scene_name("public_space") == "公共与商业空间"
    assert vocabulary.task_name("wipe_clean") == "擦拭清洁"
    assert vocabulary.task_name("human_demo") == "人体演示"
    assert vocabulary.scene_name("厨房") is None
    assert vocabulary.task_name("kitchen") is None
    # “未标注”是筛选专用值，不能与任何词表编码重名，否则“未知”和“未标注”会混淆。
    assert vocabulary.UNLABELED == "unlabeled"
    assert vocabulary.UNLABELED not in SCENE_CODES + TASK_CODES


def test_read_entry_projects_classification_fields(fake_nav: FakeNavigation) -> None:
    """契约：读取只投影顶层 scene/tasks/robot_model；缺失、空串、非文本和非文本数组项都按未标注处理。"""
    loc = location(fake_nav)
    bare = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    assert (bare.scene, bare.tasks, bare.robot_model) == (None, (), None)
    label(
        fake_nav,
        "libero_10",
        scene="tabletop",
        tasks=["pick_place", "pick_place", 3, "not_in_vocab"],
        robot_model="Franka",
    )
    full = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    # 去重保序；非文本项丢弃；不在词表的值照样保留。
    assert (full.scene, full.tasks, full.robot_model) == (
        "tabletop",
        ("pick_place", "not_in_vocab"),
        "Franka",
    )
    label(fake_nav, "libero_10", scene="")
    assert read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint).scene is None
    label(fake_nav, "libero_10", scene=5, tasks="fold")
    odd = read_entry(fake_nav.nav_root, loc, checkpoint=checkpoint)
    assert (odd.scene, odd.tasks) == (None, ())


def test_scan_indexes_custom_classification_without_notices(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：扫描把字段写进数据集索引；自定义值不产生词表提示，筛选候选显示原值。"""
    label(fake_nav, "libero_10", scene="tabletop", tasks=["pick_place"], robot_model="Franka")
    label(fake_nav, "EgoProDemo", scene="厨房", tasks=["fold", "开门"])
    with browser_case(tmp_path / "state", fake_nav) as case:
        response = case.client.get("/api/datasets")
        assert response.status_code == 200
        rows = {row["name"]: row for row in response.json()["items"]}
        assert (
            rows["libero_10"]["scene"],
            rows["libero_10"]["tasks"],
            rows["libero_10"]["robot_model"],
        ) == (
            "tabletop",
            ["pick_place"],
            "Franka",
        )
        assert (rows["EgoProDemo"]["scene"], rows["EgoProDemo"]["tasks"]) == (
            "厨房",
            ["fold", "开门"],
        )
        assert (rows["EgoProStandard"]["scene"], rows["EgoProStandard"]["tasks"]) == (None, [])
        assert rows["EgoProStandard"]["robot_model"] is None
        panel = case.client.get("/api/datasets/panel").json()
        assert all(
            item["diagnostics"]["rule"] != "VOCABULARY_UNKNOWN" for item in panel["findings"]
        )
        options = case.client.get("/api/datasets/filters").json()
        scenes = {item["value"]: item["label"] for item in options["scenes"]}
        tasks = {item["value"]: item["label"] for item in options["tasks"]}
        assert scenes["厨房"] == "厨房"
        assert tasks["开门"] == "开门"


def test_list_and_filters_by_scene_and_tasks(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：场景单选精确匹配；任务多选取交集；未标注单独一项；条件互相取交集。"""
    label(fake_nav, "libero_10", scene="tabletop", tasks=["pick_place", "tidy"])
    label(fake_nav, "EgoProDemo", scene="kitchen", tasks=["pick_place"])
    label(fake_nav, "EgoProStandard", scene="kitchen", tasks=["tidy", "fold"])
    with browser_case(tmp_path / "state", fake_nav) as case:

        def names(**params: Any) -> list[str]:
            response = case.client.get("/api/datasets", params=params)
            assert response.status_code == 200, response.text
            return [item["name"] for item in response.json()["items"]]

        assert names(scene="kitchen") == ["EgoProDemo", "EgoProStandard"]
        assert names(scene="tabletop") == ["libero_10"]
        assert names(tasks=["pick_place"]) == ["EgoProDemo", "libero_10"]
        # 交集：必须同时有 pick_place 和 tidy，只有 libero_10。
        assert names(tasks=["pick_place", "tidy"]) == ["libero_10"]
        assert names(tasks=["fold", "pick_place"]) == []
        assert names(scene="kitchen", tasks=["tidy"]) == ["EgoProStandard"]
        # 未标注：场景和任务分别单独算。
        assert names(scene="unlabeled") == ["R1_lite_table_withdrawing_mcap", "agibot_world_alpha"]
        assert names(tasks=["unlabeled"]) == [
            "R1_lite_table_withdrawing_mcap",
            "agibot_world_alpha",
        ]
        # 词表外的值不会被静默忽略：精确匹配为空集。
        assert names(scene="厨房") == []
        # 未标注与具体任务不能同时选，明确 422 而不是悄悄返回空集。
        response = case.client.get("/api/datasets", params={"tasks": ["unlabeled", "fold"]})
        assert response.status_code == 422
        assert response.json()["diagnostics"]
        item = case.client.get("/api/datasets", params={"scene": "tabletop"}).json()["items"][0]
        assert (item["scene"], item["tasks"]) == ("tabletop", ["pick_place", "tidy"])


def test_filter_options_carry_vocabulary_names_and_counts(
    tmp_path: Path, fake_nav: FakeNavigation
) -> None:
    """契约：候选含全部词表项（零计数也保留）、自定义值（显示原值）、末位的未标注；任务计数按数据集。"""
    label(fake_nav, "libero_10", scene="tabletop", tasks=["pick_place", "tidy"])
    label(fake_nav, "EgoProDemo", scene="厨房", tasks=["pick_place"])
    with browser_case(tmp_path / "state", fake_nav) as case:
        options = case.client.get("/api/datasets/filters").json()
        scenes = {item["value"]: item for item in options["scenes"]}
        assert [item["value"] for item in options["scenes"]][:10] == list(SCENE_CODES)
        assert scenes["tabletop"] == {"value": "tabletop", "label": "桌面", "count": 1}
        assert scenes["kitchen"]["count"] == 0
        assert scenes["厨房"] == {"value": "厨房", "label": "厨房", "count": 1}
        assert options["scenes"][-1] == {"value": "unlabeled", "label": "未标注", "count": 3}
        tasks = {item["value"]: item for item in options["tasks"]}
        assert tasks["pick_place"]["count"] == 2 and tasks["pick_place"]["label"] == "抓取放置"
        assert tasks["tidy"]["count"] == 1 and tasks["fold"]["count"] == 0
        assert options["tasks"][-1] == {"value": "unlabeled", "label": "未标注", "count": 3}
        # 编辑器用的词表只含词表项，不含词表外值和未标注。
        assert [item["code"] for item in options["scene_vocabulary"]] == list(SCENE_CODES)
        assert [item["code"] for item in options["task_vocabulary"]] == list(TASK_CODES)
        assert options["scene_vocabulary"][0] == {"code": "kitchen", "name": "家居-厨房"}


def test_scene_tree_groups_canonical_entries(tmp_path: Path, fake_nav: FakeNavigation) -> None:
    """契约：按场景树只含按任务规范入口；场景节点显示中文名，数量按去重数据集；筛选同样作用于它。"""
    label(fake_nav, "libero_10", scene="tabletop", tasks=["pick_place"])
    label(fake_nav, "EgoProDemo", scene="tabletop")
    with browser_case(tmp_path / "state", fake_nav) as case:
        nodes = case.client.get("/api/datasets/trees").json()["nodes"]
        assert [node["path"] for node in nodes] == sorted(node["path"] for node in nodes)
        scene = [node for node in nodes if node["view"] == "scene"]
        by_path = {node["path"]: node for node in scene}
        assert by_path["按场景"]["kind"] == "view" and by_path["按场景"]["dataset_count"] == 5
        assert by_path["按场景/tabletop"]["name"] == "桌面"
        assert by_path["按场景/tabletop"]["kind"] == "scene"
        assert by_path["按场景/tabletop"]["dataset_count"] == 2
        assert by_path["按场景/unlabeled"]["name"] == "未标注"
        assert by_path["按场景/unlabeled"]["dataset_count"] == 3
        leaves = [node for node in scene if node["kind"] == "entry"]
        assert len(leaves) == 5
        libero = next(node for node in leaves if node["name"] == "libero_10")
        assert libero["path"] == "按场景/tabletop/libero_10"
        assert libero["parent_path"] == "按场景/tabletop"
        assert libero["entry_path"] == "按任务/libero_10"
        assert libero["dataset_id"] == "dataset-14"
        # 原有两棵树的节点不变，视图字段仍是 task/format。
        assert {node["view"] for node in nodes} == {"task", "format", "scene"}
        filtered = case.client.get("/api/datasets/trees", params={"tasks": ["pick_place"]}).json()
        scene_leaves = [
            node["name"]
            for node in filtered["nodes"]
            if node["view"] == "scene" and node["kind"] == "entry"
        ]
        assert scene_leaves == ["libero_10"]


@pytest.mark.parametrize("params", [{"tasks": ["unlabeled", "fold"]}])
def test_trees_reject_conflicting_unlabeled(
    tmp_path: Path, fake_nav: FakeNavigation, params: dict[str, Any]
) -> None:
    """契约：树与列表共用筛选校验，未标注与具体任务同选也是 422。"""
    with browser_case(tmp_path / "state", fake_nav) as case:
        assert case.client.get("/api/datasets/trees", params=params).status_code == 422


@pytest.mark.parametrize("scene", ["tabletop", "..", "custom/厨房"])
def test_scene_tree_paths_are_browsable(
    tmp_path: Path, fake_nav: FakeNavigation, scene: str
) -> None:
    """契约：树返回的场景目录及叶路径均可用于列表筛选；词表外斜线和点不变成目录穿越。"""
    label(fake_nav, "libero_10", scene=scene)
    with browser_case(tmp_path / "state", fake_nav) as case:
        nodes = case.client.get("/api/datasets/trees").json()["nodes"]
        leaf = next(
            node for node in nodes if node["view"] == "scene" and node["dataset_id"] == "dataset-14"
        )
        for path in (leaf["parent_path"], leaf["path"]):
            response = case.client.get("/api/datasets", params={"entry_path": path})
            assert response.status_code == 200, response.text
            assert [item["name"] for item in response.json()["items"]] == ["libero_10"]
