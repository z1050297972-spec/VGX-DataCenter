"""场景、任务受控词表（领域层，M1.5-03）：编码加中文名称，只存常量，不读取任何文件。

词表来自 `.scratch/m1.5-edit-view-classify/vocab-draft.md`（负责人未提出修改）。平台按编码存储，
页面显示中文名称；数据集信息.json 里的值不在词表时照样保留，只在一致性面板给“提示”。

放在代码常量而不是配置文件：词表要和索引读取、筛选候选、测试一起评审（改一项就是一次契约变更），
部署配置不应静默改变筛选口径；增删一项只需改本文件的元组，并重新扫描让提示和计数更新。
当出现需要运维现场增删词表而不发版的需求时，再把两个元组换成配置读取（调用方只依赖
`SCENES`、`TASKS`、`scene_name`、`task_name`，无需改动）。
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class VocabularyTerm:
    """词表中的一项。

    Attributes:
        code: 稳定编码，小写英文加下划线，非空，同一词表内唯一；写入数据集信息.json 的就是它。
        name: 页面显示的中文名称，非空。
    """

    code: str
    name: str


# 筛选专用值：表示“没有填写”。它不是词表编码（词表里的 unknown 是“未知”，含义不同），
# 所以不会写进数据集信息.json，也不能与任何编码重名。
UNLABELED: Final = "unlabeled"
UNLABELED_NAME: Final = "未标注"

SCENES: Final = (
    VocabularyTerm("kitchen", "家居-厨房"),
    VocabularyTerm("home_living", "家居-起居"),
    VocabularyTerm("tabletop", "桌面"),
    VocabularyTerm("office", "办公室"),
    VocabularyTerm("retail", "商超零售"),
    VocabularyTerm("logistics", "物流仓储"),
    VocabularyTerm("industrial", "工业"),
    VocabularyTerm("public_space", "公共与商业空间"),
    VocabularyTerm("mixed", "多场景混合"),
    VocabularyTerm("unknown", "未知"),
)
TASKS: Final = (
    VocabularyTerm("pick_place", "抓取放置"),
    VocabularyTerm("articulated", "开合操作"),
    VocabularyTerm("fold", "折叠"),
    VocabularyTerm("wipe_clean", "擦拭清洁"),
    VocabularyTerm("tidy", "收纳整理"),
    VocabularyTerm("cook", "烹饪"),
    VocabularyTerm("mobile_nav", "移动与导航"),
    VocabularyTerm("tool_use", "工具使用"),
    VocabularyTerm("bimanual", "双臂协作"),
    VocabularyTerm("human_demo", "人体演示"),
    VocabularyTerm("long_horizon", "长程多步"),
    VocabularyTerm("unknown", "未知"),
)


def scene_name(code: str) -> str | None:
    """查场景编码对应的中文名称。

    Args:
        code: 数据集信息.json 里的 scene 值，区分大小写。

    Returns:
        词表内返回中文名称；不在词表（包括中文原值和 unlabeled）返回 None。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        纯函数，无时间输入。
    """
    return next((term.name for term in SCENES if term.code == code), None)


def task_name(code: str) -> str | None:
    """查任务编码对应的中文名称。

    Args:
        code: 数据集信息.json 里 tasks 数组的一项，区分大小写。

    Returns:
        词表内返回中文名称；不在词表返回 None。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        纯函数，无时间输入。
    """
    return next((term.name for term in TASKS if term.code == code), None)
