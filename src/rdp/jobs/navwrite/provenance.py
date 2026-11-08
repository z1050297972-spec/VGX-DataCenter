"""`来源.json` 的格式与读写（领域层，M1-07，ADR 0008）。

第 2 版只存身份、采集任务和血缘；兼容读取第 1 版并忽略其中的数据来源字段。
只在按任务入口存在，按格式入口不放副本。自动血缘只追加，人工补录可整条删除；没有文件表示来历未知。
本模块负责内存里的模型和纯函数；写盘走 NavWritePlan 的 WriteFileStep，不另开写路径。
"""

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rdp.jobs.datasets import _io
from rdp.jobs.datasets.catalog import MAX_DOCUMENT_BYTES, PROVENANCE_DOCUMENT
from rdp.jobs.datasets.types import JsonObject, ProvenanceState
from rdp.jobs.navwrite.errors import nav_external_error, nav_input_error
from rdp.jobs.navwrite.policy import PROVENANCE_FORMAT_VERSION

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class ActorStamp(BaseModel):
    """记录“谁在什么时候做的”的印记，供血缘记录使用。

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
    """一条血缘记录；写入后不再修改，M3 仅允许整条删除人工补录。

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
        ingest_check: 入库检查的结果与警告数；未做或旧记录没有这个键时为 None（默认值）。
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
    ingest_check: dict[str, str | int] | None = None
    recorded_by: ActorStamp


class ProvenanceDocument(BaseModel):
    """`来源.json` 第 2 版的完整内容；字段顺序即写出顺序。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        schema_version: 固定 2；第 1 版读取时先丢弃来源字段再转换。
        dataset_id: 永久编号，必须与入口里其他三份 JSON 一致。
        dataset_name: 数据集名，等于按任务入口的目录名。
        collection_task_id: 兼容旧采集任务编号，缺键为 None；M3 不用于关联，编辑原文时保持原样。
        lineage: 血缘记录，按 record_id 升序，空元组表示"来历未知"。
    """

    model_config = _FROZEN
    schema_version: Literal[2] = 2
    dataset_id: str = Field(min_length=1)
    dataset_name: str = Field(min_length=1)
    collection_task_id: str | None = None
    lineage: tuple[LineageRecord, ...]


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
    try:
        with _io.directory(entry_dir) as descriptor:
            return _read_in(descriptor)
    except OSError as error:
        problem = nav_external_error(
            "NAV_PROVENANCE", "入口目录无法访问", objects=(("entry_path", entry_dir.name),)
        )
        raise problem from error


def new_provenance(dataset_id: str, dataset_name: str) -> ProvenanceDocument:
    """为新数据集构造第 2 版来源文件，空血缘表示来历未知。

    Args:
        dataset_id: 非空永久编号，例如 dataset-36。
        dataset_name: 非空按任务入口目录名。

    Returns:
        第 2 版 ProvenanceDocument，collection_task_id 为 None，lineage 为空元组。

    Raises:
        ValidationError: 编号或名称为空或类型不合法。

    Side Effects:
        无；数据来源由调用方写入数据集信息.json。

    Time Semantics:
        同步纯函数，不读取时钟。
    """
    return ProvenanceDocument(
        dataset_id=dataset_id,
        dataset_name=dataset_name,
        collection_task_id=None,
        lineage=(),
    )


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
    expected = max((item.record_id for item in document.lineage), default=0) + 1
    if record.record_id != expected:
        problem = nav_input_error(
            "NAV_PROVENANCE",
            "血缘记录编号不是下一个编号",
            expected=str(expected),
            objects=(("record_id", str(record.record_id)),),
        )
        raise problem
    return document.model_copy(update={"lineage": (*document.lineage, record)})


def dump_provenance(document: ProvenanceDocument) -> JsonObject:
    """把内容转成按字段声明顺序排列的 JSON 对象，交给 dump_navigation_json 写出。

    Args:
        document: 要写出的内容。

    Returns:
        键顺序为 schema_version、dataset_id、dataset_name、
        collection_task_id、lineage；没有值的字段显式写 null，不省略；时间保持 UTC `Z` 文本。

    Raises:
        无。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    return cast(JsonObject, document.model_dump(mode="json"))


def _invalid(reason: str, digest: str | None = None) -> ProvenanceRead:
    """文件存在但不可用；不替换成空文档。"""
    return ProvenanceRead(ProvenanceState.INVALID, None, digest, reason)


def _read_in(descriptor: int) -> ProvenanceRead:
    """在已打开的入口目录里读来源.json，不跟随软链接。"""
    try:
        fd = os.open(
            PROVENANCE_DOCUMENT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
    except FileNotFoundError:
        return ProvenanceRead(ProvenanceState.ABSENT, None, None, None)
    except OSError as error:
        reason = "来源.json 是软链接，不读取" if error.errno == 40 else "来源.json 无法打开"
        return _invalid(reason)
    try:
        content = _read_regular(fd)
    except (OSError, _Unusable) as error:
        return _invalid(str(error) if isinstance(error, _Unusable) else "来源.json 读取失败")
    finally:
        os.close(fd)
    return _parse(content)


class _Unusable(Exception):  # noqa: N818  # 理由：文件级问题的内部信号，只在本模块捕获并转成 INVALID。
    """来源.json 不是可读的普通文件或超过大小上限；消息就是给人看的原因。"""


def _read_regular(fd: int) -> bytes:
    """读普通文件原字节，有大小上限。"""
    if not stat.S_ISREG(os.fstat(fd).st_mode):
        raise _Unusable("来源.json 不是普通文件")
    content = b""
    while len(content) <= MAX_DOCUMENT_BYTES:
        block = os.read(fd, 1024 * 1024)
        if not block:
            return content
        content += block
    raise _Unusable("来源.json 超过大小上限")


def _parse(content: bytes) -> ProvenanceRead:
    """兼容第 1 版并校验第 2 版格式；任何一步不合格都是 INVALID，不替换成空文档。"""
    digest = hashlib.sha256(content).hexdigest()
    try:
        loaded = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _invalid("来源.json 不是合法的 UTF-8 JSON", digest)
    if not isinstance(loaded, dict):
        return _invalid("来源.json 顶层不是对象", digest)
    payload = cast(JsonObject, loaded)
    version = payload.get("schema_version")
    if type(version) is not int or version not in (1, PROVENANCE_FORMAT_VERSION):
        return _invalid("来源.json 的 schema_version 不认识", digest)
    if version == 1:
        # 旧字段不再拥有显示或筛选语义，也不要求它们仍满足旧编辑契约。
        payload.pop("data_origin", None)
        payload.pop("data_origin_set_by", None)
        payload["schema_version"] = PROVENANCE_FORMAT_VERSION
    try:
        document = ProvenanceDocument.model_validate(payload)
    except ValidationError:
        return _invalid("来源.json 的字段不符合第 2 版格式", digest)
    return ProvenanceRead(ProvenanceState.VALID, document, digest, None)
