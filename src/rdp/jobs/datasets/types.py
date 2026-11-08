"""数据集读取值对象（领域层，M1-01）；描述导航事实与解析结果，不执行文件或数据库 I/O。

JSON 用标准库兼容的递归类型保留未知字段；推导值另存，绝不覆写原载荷。
损坏入口用位置展示，不能伪造永久 dataset_id；规范副本缺失也不把格式入口提升为规范副本。
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath

from rdp.collection.information import CollectionInformation
from rdp.infra.diagnostics import Diagnostic, DiagnosticGroup

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
type JsonObject = dict[str, JsonValue]


class View(StrEnum):
    """由位置推导的两个视图，不能由 JSON 内字段决定。"""

    TASK = "task"
    FORMAT = "format"


class ProvenanceState(StrEnum):
    """来源.json 的读取结果种类（三态）；读取与校验由 navwrite.provenance 负责。

    Attributes:
        ABSENT: absent，文件不存在，按"未知"处理。
        VALID: valid，解析并通过校验。
        INVALID: invalid，存在但无法解析、不是普通文件或版本不认识；写入作业必须拒绝覆盖。
    """

    ABSENT = "absent"
    VALID = "valid"
    INVALID = "invalid"


class PanelSeverity(StrEnum):
    """面板两级；不等同作业成功失败计数（11 Q14）。"""

    ACTION_REQUIRED = "action_required"
    NOTICE = "notice"


class PanelGroup(StrEnum):
    """面板四组；存储相关两组由扫描第二段提供。"""

    JSON = "json"
    VIEWS = "views"
    DISK = "disk"
    STORAGE = "storage"


@dataclass(frozen=True)
class Finding:
    """一条面板发现，五段内容始终复用 Diagnostic。

    Attributes:
        group: 四个检查组之一。
        severity: 需要处理或提示，不直接决定作业结果。
        diagnostic: 五段诊断；rule 为稳定规则码，objects 含入口路径和已知 dataset_id。
            需要处理映射 ERROR，提示映射 WARNING；这种展示映射不累计作业失败。
    """

    group: PanelGroup
    severity: PanelSeverity
    diagnostic: Diagnostic


@dataclass(frozen=True)
class FindingGroup:
    """按组、级别、来源、规则聚合的面板发现。

    Attributes:
        group: 四组之一。
        severity: 两级之一。
        diagnostics: 复用既有 DiagnosticGroup，完整计数，前 DIAGNOSTIC_SAMPLE_LIMIT 条样例。
    """

    group: PanelGroup
    severity: PanelSeverity
    diagnostics: DiagnosticGroup


@dataclass(frozen=True)
class EntryLocation:
    """不依赖 JSON 的入口身份，坏文件仍可按位置显示。

    Attributes:
        path: 相对 nav_root 的 POSIX 路径，不含空分量、..，不经软链接。
        view: 按任务或按格式。
        format: 格式稳定键；按任务为 None。
        version: 格式版本非空文本；无版本层或按任务为 None。
        dataset_name: 最后一层目录名，原样保留中文、空格、括号和撇号。
    """

    path: PurePosixPath
    view: View
    format: str | None
    version: str | None
    dataset_name: str


@dataclass(frozen=True)
class NavigationCatalog:
    """只遍历登记视图得到的入口清单。

    Attributes:
        entries: 按相对路径 Unicode 升序，允许空；空版本目录不是入口。
        findings: 顶层或格式目录未知等发现，按对象路径和规则排序。
    """

    entries: tuple[EntryLocation, ...]
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class JsonDocument:
    """一份文件的原始内容与可用性，不把坏文件替换成空对象。

    Attributes:
        name: REQUIRED_DOCUMENTS 中的文件名。
        payload: 解析并验证依赖字段后的原对象，未知字段和省略字段不变；不可用为 None。
        sha256: 读到的原始字节摘要，64位小写十六进制；无法读取时 None。
        schema_version: 缺省归一为1；无法解析或版本不支持时 None。
        findings: 文件不可用的五段诊断；合法文件为空元组。
    """

    name: str
    payload: JsonObject | None
    sha256: str | None
    schema_version: int | None
    findings: tuple[Finding, ...]


@dataclass(frozen=True)
class Link:
    """JSON 中声明的一条链接，不读取目标。

    Attributes:
        name: 非空单层链接名。
        source_path: JSON 声明的绝对目标路径文本，不 resolve。
        source_type: 原样保留的目标类型文本，如 directory/file。
        entry_path: 按入口位置和 name 推导的导航相对路径。
    """

    name: str
    source_path: str
    source_type: str
    entry_path: str


@dataclass(frozen=True)
class Source:
    """一个入口的原始数据块记录，不合并两个视图的不同载荷。

    Attributes:
        source_id: 既有永久编号，非空，不重算；重复仍保留并报告。
        original_path: 首次登记绝对路径；不检查存在性。
        direct_path: 当前绝对路径，本票只保存文本。
        entry_path: 位置推导值；无链接覆盖时仍为 direct_path 绝对文本。
        format: 原样格式文本，未知或缺失为 None。
        version: 省略与 null 均为 None，否则保留文本。
        validation_status: 原样核验状态，缺失为 None，不按当前扫描重写。
    """

    source_id: str
    original_path: str
    direct_path: str
    entry_path: str
    format: str | None
    version: str | None
    validation_status: str | None


@dataclass(frozen=True)
class EntrySnapshot:
    """一个入口的有限读取快照，与 JSON 未知字段一同交给面板及索引。

    Attributes:
        location: 从目录推导的唯一位置。
        documents: 按 REQUIRED_DOCUMENTS 顺序三项，失败文件也占一项。
        dataset_id: 原始路径、信息、子任务依次取首个可用文件的非空编号；全不可用为 None。
            不一致仍报告全部原值，不据目录名编造编号。
        dataset_roots: 原始路径中的绝对路径文本，顺序不变；该文件不可用为空。
        links: 原始路径清单顺序，文件不可用为空。
        sources: 原始路径清单顺序，保留重复编号供诊断；文件不可用为空。
        provenance_present: 来源.json 的目录项存在性，包括不可读/软链接；不解析内容。
        recorded_size_bytes: 兼容旧索引的字段；不再解析第4项，固定为 None。
        findings: 读取和记录值提取发现，空表示这两个步骤无发现。
        provenance_state: 来源.json 的三态（M1-07）：不存在、可读、无法读取；与
            provenance_present 并存，后者仍只表示目录项有无。默认 ABSENT，只加不改。
        data_origin: 信息顶层中文来源映射的筛选编码；缺失或非法为 unknown。
        collection: 有效采集信息；缺失或格式非法为 None。
        scene: 顶层 scene 的场景集合，兼容旧字符串；去空格、去空项、去重保序，不可用为空元组
            （M1.5-03）。不校验是否在词表内，词表外的值照样保留。
        tasks: 顶层 tasks 数组里的非空文本项，去重并保持原顺序；缺失或不是数组为空元组。
        robot_model: 顶层 robot_model 去首尾空白后的非空文本；未填写为 None。
        fps: 信息顶层正整数帧率，单位帧/秒；缺失或非法为 None。
    """

    location: EntryLocation
    documents: tuple[JsonDocument, ...]
    dataset_id: str | None
    dataset_roots: tuple[str, ...]
    links: tuple[Link, ...]
    sources: tuple[Source, ...]
    provenance_present: bool
    recorded_size_bytes: int | None
    findings: tuple[Finding, ...]
    provenance_state: ProvenanceState = ProvenanceState.ABSENT
    data_origin: str = "unknown"
    scene: tuple[str, ...] = ()
    tasks: tuple[str, ...] = ()
    robot_model: str | None = None
    fps: int | None = None
    collection: CollectionInformation | None = None
