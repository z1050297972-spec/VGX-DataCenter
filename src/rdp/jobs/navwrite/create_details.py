"""创建操作给前端看的结构化差异（领域层，M1-08）；不暴露计划中的 JSON 全文。

由 builder 在生成同一份计划时填充，随 PlanReport 保存；读取预览时不重新作决定。
计数、检查范围与有界诊断继续使用第 07 张的 PlanReport。
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rdp.jobs.datasets.catalog import MAX_SCAN_ENTRIES


class CreationDetailValue(BaseModel):
    """冻结且拒绝多余字段的预览差异。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class LinkAddition(CreationDetailValue):
    """计划创建的一条绝对目标软链接。

    Attributes:
        path: 相对导航根的完整链接位置。
        target_path: 通过 L1 校验的绝对目标路径。
    """

    path: str
    target_path: str


class SourceAddition(CreationDetailValue):
    """规范副本 sources[] 新增的数据块；已有 source_id 永不重算。

    Attributes:
        source_id: 导航层手册第 2 节的 src_ 加 original_path 的 UTF-8 字节 sha256 前 12 位。
        original_path: 首次登记的绝对路径，与新增时 direct_path 相同。
        direct_path: 当前目标绝对路径。
        format: 元信息或用户选择得到的登记格式稳定键。
        version: 元信息里的格式版本；缺文件时明确为 None。
        validation_status: 固定 path_exists_only；预览不声称完成深度质检。
    """

    source_id: str = Field(pattern=r"^src_[0-9a-f]{12}$")
    original_path: str
    direct_path: str
    format: str
    version: str | None
    validation_status: Literal["path_exists_only"] = "path_exists_only"


class CreationDetails(CreationDetailValue):
    """两种创建操作共享的展示差异，各路径清单完整且受既有扫描预算限制。

    Attributes:
        canonical_entry_path: 按任务入口的导航相对路径。
        format_entry_paths: 实际重生成的全部按格式入口路径，按路径排序；含未勾选的已有入口。
        selected_format_entry_paths: 用户本次勾选的入口路径；有目标时加入链接，可为空。
        file_paths: 所有 WriteFileStep 的路径，按执行顺序；不含文件全文。
        directory_paths: 所有 MakeDirStep 的路径，按父目录到子目录顺序；可为空。
        links: 所有 SetLinkStep 的位置和目标，按执行顺序；no-op 时为空。
        sources_added: 规范副本新增的数据块，至多一条；覆盖已有数据块时为空。
        dataset_roots_added: 要追加的绝对根路径，至多一条；已覆盖时为空。
        resolved_format: 本条目标的格式稳定键；noop 或无链接时为 None。
        resolved_version: 本条目标的版本，无 meta/info.json 时为 None。
        metadata_source: meta_info 表示使用文件；selected_format 表示缺文件后用用户选择；
            not_checked 用于 noop 或无链接，不强迫无变化请求补选格式。
        noop: L2 已有同目标且已登记时为 True，所有写入步骤及差异清单为空。
    """

    canonical_entry_path: str
    format_entry_paths: tuple[str, ...] = Field(max_length=MAX_SCAN_ENTRIES)
    selected_format_entry_paths: tuple[str, ...] = Field(max_length=MAX_SCAN_ENTRIES)
    file_paths: tuple[str, ...]
    directory_paths: tuple[str, ...]
    links: tuple[LinkAddition, ...]
    sources_added: tuple[SourceAddition, ...] = Field(max_length=1)
    dataset_roots_added: tuple[str, ...] = Field(max_length=1)
    resolved_format: str | None
    resolved_version: str | None
    metadata_source: Literal["meta_info", "selected_format", "not_checked"]
    noop: bool
