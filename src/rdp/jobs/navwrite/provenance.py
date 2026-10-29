"""`来源.json` 的格式与读写（领域层，M1-07，ADR 0008）。

第 1 版格式以 15 号票的草样为起点：去掉 `_example_platform_record`，其余字段保留。
只在按任务入口存在，按格式入口不放副本。血缘记录只追加；数据来源可以改，改的时候记下是谁、什么时候改的。
没有这份文件的数据集按"数据来源未知、来历未知"处理（一致性面板只给提示）。
本模块负责内存里的模型和纯函数；写盘走 NavWritePlan 的 WriteFileStep，不另开写路径。
"""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rdp.jobs.datasets.types import JsonObject

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ActorStamp(BaseModel):
    """记录“谁在什么时候做的”的印记，数据来源和血缘记录共用。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        kind: 人工标注、人工补录、平台自动、worker 四种之一。
        account_id: 账号内部编号，≥ 1；平台自动或 worker 为 None。
        account_name: 当时的账号显示名快照，1-64 码点；平台自动或 worker 为 None。
        at: UTC 时刻，ISO 8601 以 `Z` 结尾的文本，秒精度。
    """

    model_config = _FROZEN
    kind: Literal["人工标注", "人工补录", "平台自动", "worker"]
    account_id: int | None = Field(ge=1)
    account_name: str | None = Field(min_length=1, max_length=64)
    at: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class LineageRecord(BaseModel):
    """一条血缘记录；写入后不再修改，只能追加新的。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        record_id: 记录编号，从 1 起逐条加 1，文件内唯一。
        kind: 记录种类：转换、下载、采集。
        status: 完整，或来历部分未知（平台接管前产生、信息缺失的补录）。
        note: 补充说明，可为 None。
        inputs: 输入的 (dataset_id, source_id) 对；下载或采集可为空。
        outputs: 产物的 (source_id, format, codebase_version) 三元组。
        tool: 工具名、版本、git 提交号；未知项为 None。
        config: 配置文件路径、sha256 和全文；未知为 None。
        robot_profile: 机器人档案的型号、文件、版本；未知为 None。
        parameters: 命令参数，键值为 JSON 标量；未知为 None。
        job_id: 产生它的作业编号，≥ 1；未知为 None。
        started_at: UTC 开始时刻文本；未知为 None。
        finished_at: UTC 结束时刻文本；未知为 None。
        ingest_check: 入库检查的结果与警告数；未做为 None。
        recorded_by: 记录人印记。
    """

    model_config = _FROZEN
    record_id: int = Field(ge=1)
    kind: Literal["转换", "下载", "采集"]
    status: Literal["完整", "来历部分未知"]
    note: str | None
    inputs: tuple[dict[str, str], ...]
    outputs: tuple[dict[str, str | None], ...]
    tool: dict[str, str | None] | None
    config: dict[str, str] | None
    robot_profile: dict[str, str | int] | None
    parameters: dict[str, str | int | float | bool | None] | None
    job_id: int | None = Field(ge=1)
    started_at: str | None
    finished_at: str | None
    ingest_check: dict[str, str | int] | None
    recorded_by: ActorStamp


class ProvenanceDocument(BaseModel):
    """`来源.json` 第 1 版的完整内容；字段顺序即写出顺序。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        schema_version: 固定 1；读到更大的版本一律拒绝解析。
        dataset_id: 永久编号，必须与入口里其他三份 JSON 一致。
        dataset_name: 数据集名，等于按任务入口的目录名。
        data_origin: 取值为 DATA_ORIGINS 之一（真机采集、UMI 采集、ego 采集、仿真生成、开源下载、未知）。
        data_origin_set_by: 最后一次设置数据来源的印记；"未知"且从未标注时为 None。
            旧值不留在文件里，历史靠变更记录追溯。
        collection_task_id: 所属采集任务的编号文本，没有为 None（采集任务编号形式由 M2 定）。
        lineage: 血缘记录，按 record_id 升序，空元组表示"来历未知"。
    """

    model_config = _FROZEN
    schema_version: Literal[1] = 1
    dataset_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    data_origin: str = Field(min_length=1)
    data_origin_set_by: ActorStamp | None
    collection_task_id: str | None
    lineage: tuple[LineageRecord, ...]


class ProvenanceState(StrEnum):
    """读一份来源.json 的结果种类。

    Attributes:
        ABSENT: absent，文件不存在，按"未知"处理。
        VALID: valid，解析并通过校验。
        INVALID: invalid，存在但无法解析或版本不认识；写入作业必须拒绝覆盖。
    """

    ABSENT = "absent"
    VALID = "valid"
    INVALID = "invalid"


@dataclass(frozen=True)
class ProvenanceRead:
    """读取来源.json 的结果，坏文件不被替换成空文档。

    Attributes:
        state: 读取结果种类。
        document: state 为 VALID 时的内容，否则 None。
        sha256: 文件存在时原字节的 64 位小写摘要，用于预览状态核对；缺失为 None。
        reason: state 为 INVALID 时的原因（中文，不含正文），否则 None。
    """

    state: ProvenanceState
    document: ProvenanceDocument | None
    sha256: str | None
    reason: str | None


def read_provenance(entry_dir: Path) -> ProvenanceRead:
    """读取按任务入口里的来源.json，替代第 01 张"只看有没有"的做法。

    Args:
        entry_dir: 按任务入口目录的绝对路径，路径分量不得是软链接。

    Returns:
        ProvenanceRead。文件不存在为 ABSENT；是软链接、非普通文件、超过 MAX_DOCUMENT_BYTES、
        不是合法 JSON、schema_version 不认识或字段不合格为 INVALID，并给出原因。

    Raises:
        ExternalError: 入口目录本身无法访问（权限、I/O 错误）；文件级问题用 INVALID 表达，不抛。

    Side Effects:
        无（只读，用 O_NOFOLLOW 打开，不跟随软链接）。

    Time Semantics:
        同步读取，单个文件有大小上限；不读墙钟。
    """
    raise NotImplementedError


def new_provenance(
    dataset_id: str, dataset_name: str, origin: str, set_by: ActorStamp | None
) -> ProvenanceDocument:
    """为一个还没有来源.json 的数据集构造第一份内容，血缘为空表示"来历未知"。

    Args:
        dataset_id: 永久编号，非空，如 `dataset-36`。
        dataset_name: 按任务入口目录名，非空。
        origin: 数据来源，必须在 DATA_ORIGINS 里；新增数据集时由用户必填，补写旧数据集时可为"未知"。
        set_by: 设置者印记；origin 为"未知"且无人标注时传 None，其余必须有值。

    Returns:
        ProvenanceDocument：`collection_task_id` 为 None，`lineage` 为空元组。

    Raises:
        InputError: origin 不在取值表里，或 origin 不是"未知"却没有 set_by。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数；时刻由调用方放进 set_by.at，函数本身不读时钟。
    """
    raise NotImplementedError


def with_data_origin(
    document: ProvenanceDocument, origin: str, set_by: ActorStamp
) -> ProvenanceDocument:
    """改数据来源，并记下是谁、什么时候改的；血缘和其他字段不动。

    Args:
        document: 现有内容。
        origin: 新的数据来源，必须在 DATA_ORIGINS 里。
        set_by: 本次修改者印记，kind 为"人工标注"或"人工补录"。

    Returns:
        新 ProvenanceDocument：`data_origin` 与 `data_origin_set_by` 被替换，`lineage` 原样。
        新旧来源相同时仍更新印记，不静默忽略；调用方要避免空写入就先比较。

    Raises:
        InputError: origin 不在取值表里，或 set_by.kind 不是人工类。

    Side Effects:
        无；返回新对象。

    Time Semantics:
        同步纯函数；set_by.at 由调用方的注入时钟生成。
    """
    raise NotImplementedError


def with_lineage_record(document: ProvenanceDocument, record: LineageRecord) -> ProvenanceDocument:
    """追加一条血缘记录；已有记录一条都不改。

    Args:
        document: 现有内容。
        record: 要追加的记录；其 record_id 必须等于现有最大 record_id 加 1（空血缘时为 1）。

    Returns:
        新 ProvenanceDocument：`lineage` 末尾多一条，其余字段原样。

    Raises:
        InputError: record_id 不是下一个编号（会造成覆盖或空号）。

    Side Effects:
        无；返回新对象，不改 document。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError


def dump_provenance(document: ProvenanceDocument) -> JsonObject:
    """把内容转成按字段声明顺序排列的 JSON 对象，交给 dump_navigation_json 写出。

    Args:
        document: 要写出的内容。

    Returns:
        键顺序为 schema_version、dataset_id、dataset_name、data_origin、data_origin_set_by、
        collection_task_id、lineage；没有值的字段显式写 null，不省略；时间保持 UTC `Z` 文本。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError
