"""数据集浏览的请求与展示契约（领域层，M1-03），不依赖 HTTP、ORM 或文件访问。

使用已批准的 Pydantic 生成 OpenAPI；原始 JSON 用文本保留字段、空白和未知版本，
推导值独立返回。集合有界；索引未检查、记录缺失和实际零字节保持不同含义。
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from rdp.infra.diagnostics import Diagnostic
from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES
from rdp.jobs.datasets.types import FindingGroup, ProvenanceState, View
from rdp.jobs.navwrite.policy import DATA_ORIGINS

# M1-03：每页最多100项，树受已有扫描入口预算限制；不截断并冒充完整树。
BROWSER_PAGE_LIMIT = 100
# 和已合并 RescanParameters 的编号约束一致；不导入包含执行函数的 rescan 模块。
DatasetId = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^[^/\\\s\x00]+$")]
# 相对路径只做文本传输；实际打开还须按索引查找并逐分量 O_NOFOLLOW。
EntryPath = Annotated[str, Field(min_length=1, pattern=r"^[^\x00]+$")]
Layout = Literal["A", "B", "C"]


class BrowserValue(BaseModel):
    """冻结展示值，拒绝多余字段，校验错误不回显请求载荷。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class DataOrigin(StrEnum):
    """13 Q5 的六种来源编码；来源文件中文值由扫描映射到这些稳定编码。"""

    REAL = "real"
    UMI = "umi"
    EGO = "ego"
    SIMULATION = "simulation"
    OPEN_SOURCE = "open_source"
    UNKNOWN = "unknown"


class DatasetFilters(BrowserValue):
    """所有树/列表共享的筛选；不同维度 AND，同一维度匹配任一数据块。

    未提供表示不限；unknown 是独立的未知项。型号标签精确且区分大小写，
    型号按已登记标签并集匹配；型号 unknown 指没有任何已映射标签（不等于标签未知）。
    元信息以规范入口为准；无规范入口取全部格式入口并集，重复规范入口不任取。
    FPS 用索引 fps_rounded，29.97→30、30.5→31，不能重新读 meta/info.json。
    空来源、无数据块、非 LeRobot 或未检查元信息都具有未知项；混合已知/未知均可匹配。
    """

    robot_model_id: str | None = Field(
        default=None, min_length=1, description="型号编号或 unknown；空表时指定编号返回空集"
    )
    robot_type: str | None = Field(
        default=None, min_length=1, description="原始型号标签或 unknown；不解析 Markdown"
    )
    fps: Annotated[int, Field(ge=0)] | Literal["unknown"] | None = Field(
        default=None, description="四舍五入后非负整数帧/秒或 unknown"
    )
    data_origin: DataOrigin | None = None
    view: View | None = None
    format: str | None = Field(
        default=None, min_length=1, description="格式稳定键，如 lerobot；与 view=task 同用时422"
    )
    version: str | None = Field(
        default=None, min_length=1, description="格式版本；提供时必须同时给 format"
    )
    entry_path: EntryPath | None = Field(
        default=None, description="树选中节点的相对路径，按完整路径分量前缀筛选"
    )


class DatasetListQuery(DatasetFilters):
    """固定按名称、身份和入口路径 Unicode 升序的分页；offset 越过末尾返回空页。"""

    offset: int = Field(default=0, ge=0, le=MAX_SCAN_ENTRIES)
    limit: int = Field(default=BROWSER_PAGE_LIMIT, ge=1, le=BROWSER_PAGE_LIMIT)


class RobotModelOption(BrowserValue):
    """登记型号的最小只读投影；一个标签最多属于一个型号，停用型号仍能筛历史数据。"""

    model_id: str = Field(min_length=1, description="平台永久编号文本，不接受标签冒充")
    name: str = Field(min_length=1)
    robot_types: tuple[str, ...] = Field(description="去重排序的对应标签，允许空")


class FilterOption(BrowserValue):
    """筛选值及中文标签；count 是全索引中匹配的数据集数，不重复计跨视图副本。"""

    value: str
    label: str
    count: int = Field(ge=0)


class DatasetFilterOptions(BrowserValue):
    """未应用当前筛选的全局候选；所有列表按值排序，未知项固定最后且即使零项也保留。"""

    robot_models_registered: bool
    default_robot_filter: Literal["robot_model", "robot_type"]
    robot_models: tuple[RobotModelOption, ...]
    robot_model_options: tuple[FilterOption, ...]
    robot_types: tuple[FilterOption, ...]
    fps: tuple[FilterOption, ...] = Field(
        description="value 为整数十进制文本或 unknown；已知按数值排序"
    )
    data_origins: tuple[FilterOption, ...]


class DatasetSize(BrowserValue):
    """单入口/数据集大小；有统计值优先，否则10-12记录值，均无则明确未知。"""

    size_bytes: int | None = Field(ge=0, description="统计表观字节数；未统计为null，离线保留旧值")
    size_checked_at: AwareDatetime | None
    recorded_size_bytes: int | None = Field(ge=0)
    recorded_on: Literal["2026-10-12"] = "2026-10-12"
    display_bytes: int | None = Field(ge=0)
    display_source: Literal["measured", "recorded", "unknown"]


class TreeSize(BrowserValue):
    """按入口求和的树大小；部分未知时不把已知小计冒充总量。"""

    known_bytes: int = Field(ge=0, description="有统计值取统计值、否则取记录值后的已知小计，字节")
    total_bytes: int | None = Field(ge=0, description="unknown_entry_count>0 时为null；空树为0")
    measured_entry_count: int = Field(ge=0)
    recorded_entry_count: int = Field(ge=0)
    unknown_entry_count: int = Field(ge=0)
    oldest_size_checked_at: AwareDatetime | None
    newest_size_checked_at: AwareDatetime | None


class EntrySummary(BrowserValue):
    """跨视图定位及列表大小；路径只作导航标识，不能由浏览器直接打开存储根。"""

    entry_path: EntryPath
    dataset_id: str | None
    name: str
    view: View
    format: str | None
    version: str | None
    size: DatasetSize


class DatasetListItem(BrowserValue):
    """已知编号按数据集去重，损坏入口逐个列出；不可伪造永久编号。"""

    dataset_id: str | None
    name: str
    canonical_entry_path: str | None
    entries: tuple[EntrySummary, ...] = Field(
        description="全部关联入口按路径排序，供跨视图跳转；无身份时恰好一项"
    )
    robot_types: tuple[str | None, ...]
    robot_model_ids: tuple[str, ...]
    fps: tuple[int | None, ...]
    data_origin: DataOrigin
    size: DatasetSize = Field(
        description="数据集取按任务入口；无唯一规范入口时未知，不叠加格式副本"
    )
    indexed_at: AwareDatetime


class DatasetListResponse(BrowserValue):
    """单次索引事务的一页；筛选只决定是否入选，entries 保留完整跨视图位置。"""

    items: tuple[DatasetListItem, ...]
    total: int = Field(ge=0)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1, le=BROWSER_PAGE_LIMIT)
    indexed_at: AwareDatetime | None = Field(
        description="当前成功扫描发布时刻；未扫描为null，行内时刻可能更旧"
    )


class DatasetTreeNode(BrowserValue):
    """平铺树节点，parent_path 用于三栏树、大表和逐级目录；按路径排序。"""

    path: str
    parent_path: str | None
    name: str
    kind: Literal["view", "format", "version", "entry"]
    view: View
    format: str | None
    version: str | None
    dataset_id: str | None
    entry_path: str | None = Field(description="仅入口节点非空，可直接请求详情")
    dataset_count: int = Field(ge=0, description="节点下已知永久编号去重数；未知身份不虚构编号")
    entry_count: int = Field(ge=0, description="含损坏入口；与dataset_count不同，大小按此口径求和")
    size: TreeSize


class DatasetTreesResponse(BrowserValue):
    """两棵树各保留一个视图根，空索引仍可浏览；最多 MAX_SCAN_ENTRIES 个入口。"""

    nodes: tuple[DatasetTreeNode, ...]
    indexed_at: AwareDatetime | None


class IndexedStorageRoot(BrowserValue):
    """扫描记录的根状态；不调用实时挂载或存储访问接口，未检查不能报离线。"""

    name: str
    path: str
    online: bool | None
    reason: Literal["not_mounted", "source_mismatch", "timeout"] | None
    checked_at: AwareDatetime | None


class DatasetPanelResponse(BrowserValue):
    """四组两级按组/级别/来源/规则合并，DiagnosticGroup.total 完整、样例复用既有上限。"""

    findings: tuple[FindingGroup, ...]
    storage_roots: tuple[IndexedStorageRoot, ...] = Field(
        description="顶部提示使用最近发布扫描的离线根；各项保留实际检查时间"
    )
    indexed_at: AwareDatetime | None


class NavigationDocument(BrowserValue):
    """导航文件原文；非UTF-8或不可读时content为空并附诊断，坏JSON文本仍可查看。"""

    name: Literal["原始路径.json", "数据集信息.json"]
    entry_path: EntryPath
    content: str | None = Field(
        description="UTF-8原文，保留空白、未知键和省略字段；不得用索引副本替代"
    )
    sha256: str | None
    usable: bool = Field(description="按第01张宽松契约可解析；false 不等于 content 一定为空")
    diagnostics: tuple[Diagnostic, ...]


class DatasetLink(BrowserValue):
    """索引链接状态与原检查时间，顺序为入口 links 数组顺序。"""

    ordinal: int = Field(ge=0)
    name: str
    source_path: str
    source_type: str
    derived_entry_path: str
    observed_target: str | None
    storage_root_name: str | None
    status: Literal[
        "unchecked", "available", "missing", "broken", "offline", "mismatch", "unregistered"
    ]
    checked_at: AwareDatetime | None
    size_bytes: int | None = Field(ge=0)
    size_checked_at: AwareDatetime | None


class DatasetSource(BrowserValue):
    """当前原始路径文件的推导字段及历史核验中文标签；不检查 original_path。"""

    ordinal: int = Field(ge=0)
    source_id: str
    original_path: str
    direct_path: str
    derived_entry_path: str
    format: str | None
    version: str | None
    validation_status: str | None
    validation_status_label: str = Field(
        description="手册第5节五个中文标签；缺失为未知，未知原值为未识别（保留原值）"
    )


class DataOriginAttribution(BrowserValue):
    """最近一次标注的公开印记，不暴露无需展示的账号内部编号。"""

    account_name: str | None = Field(description="标注时的账号名快照；平台自动设置时可为空")
    at: str = Field(description="来源文件中的 UTC ISO 8601 秒精度时刻，不使用文件 mtime")


class DatasetProvenance(BrowserValue):
    """规范入口的当前来源观察，缺文件与坏文件保持不同状态。"""

    state: ProvenanceState
    data_origin: str = Field(default="未知", json_schema_extra={"enum": list(DATA_ORIGINS)})
    data_origin_set_by: DataOriginAttribution | None = None


class DatasetDetailResponse(BrowserValue):
    """入口详情保留原文和规范信息，子任务正文只由独立接口提供。"""

    entry: EntrySummary
    entries: tuple[EntrySummary, ...]
    canonical_entry_path: str | None
    original_paths: NavigationDocument
    information: NavigationDocument = Field(description="当前入口原文，布局C查看所选文件时使用")
    canonical_information: NavigationDocument | None = Field(
        description="14项业务展示以此规范副本为准；缺失/重复规范入口为null，不将格式副本冒充规范副本"
    )
    sources: tuple[DatasetSource, ...]
    links: tuple[DatasetLink, ...] = Field(description="索引快照，不与本次原文混称同一时刻")
    dataset_size: DatasetSize
    subtasks_entry_path: EntryPath = Field(
        description="请求 /api/datasets/subtasks 时使用；正文不预加载"
    )
    index_stale: bool = Field(description="本次L12指纹不同或任一不可验证即true，不比较mtime新旧")
    indexed_at: AwareDatetime
    observed_at: AwareDatetime = Field(
        description="服务端本次请求UTC时刻，不伪装为全文件原子快照时间"
    )
    diagnostics: tuple[Diagnostic, ...]
    provenance: DatasetProvenance | None = Field(
        default=None, description="本次只读规范入口来源文件的来源与标注印记；无唯一规范入口时不可用"
    )


class LayoutRequest(BrowserValue):
    """当前账号的布局选择，不接受account_id或会话标识。"""

    layout: Layout


class LayoutResponse(BrowserValue):
    """无偏好行时返回A和null；GET不创建记录。"""

    layout: Layout
    updated_at: AwareDatetime | None
