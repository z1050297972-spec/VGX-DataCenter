"""导航目录登记（领域层，11 Q3/Q7、12 L7）；只保存已批准规则，不读取用户配置。

两表是导航协议的一部分，改动须随规则评审；不可由部署配置静默改变扫描边界。
标准库 frozen dataclass、tuple 和 frozenset 足够表达这些固定规则。
"""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class FormatDirectory:
    """一个格式目录的解释规则。

    Attributes:
        directory: 按格式下的单层目录名，非空，不含路径分隔符。
        format: 格式的稳定键，lerobot/mcap/archives。
        has_versions: True 表示数据集入口之前还有一层格式版本目录。
    """

    directory: str
    format: str
    has_versions: bool


# 11 Q3：保留原目录名，压缩包目录通过映射得到 archives。
FORMAT_DIRECTORIES: Final = (
    FormatDirectory("lerobot", "lerobot", True),
    FormatDirectory("mcap", "mcap", False),
    FormatDirectory("tar、tar.gz（含分卷）", "archives", False),
)
# 12 L7 比旧手册多一个已移除目录；只识别其名字，不进入目录读取。
NON_DATASET_DIRECTORIES: Final = frozenset({"索引", "文档", "工具", "解压样本", "已移除"})
# 三份读取文件与第四份存在性检查来自 M1-01；指纹还覆盖入口内其他 .json 文件。
REQUIRED_DOCUMENTS: Final = ("原始路径.json", "数据集信息.json", "子任务.json")
PROVENANCE_DOCUMENT: Final = "来源.json"
# ADR 0006 每十分钟提交全量扫描，单位秒；不复用 M0 每日作业的日期去重规则。
RESCAN_INTERVAL_S: Final = 600
RESCAN_TYPE: Final = "dataset_rescan"
RESCAN_NAME: Final = "重新扫描数据集"
# 0010 最大单文件约14 MB、全导航JSON约38 MB；留余量并限制恶意/意外输入占用。
MAX_DOCUMENT_BYTES: Final = 32 * 1024 * 1024
MAX_SCAN_BYTES: Final = 128 * 1024 * 1024
MAX_SCAN_ENTRIES: Final = 10_000
MAX_ENTRY_MEMBERS: Final = 100_000
