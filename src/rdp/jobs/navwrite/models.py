"""写入计划、预览状态与预览报告的值对象（领域层，M1-07、ADR 0009 L12/L13）。

只描述数据，不做 I/O。全部是冻结的 Pydantic 模型，用 model_dump_json / model_validate_json 存取，
这就是预览文件（nav-previews）与写入日志（nav-journal）共用的磁盘编码；同一份计划
由预览、执行、报告共用，不各自重算（规范 2.2）。步骤里的路径都是相对 nav_root 的 POSIX 路径。
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from rdp.jobs.datasets.fingerprint import DatasetFingerprint
from rdp.jobs.navwrite.create_details import CreationDetails

_FROZEN = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class NavOperation(StrEnum):
    """写导航层的操作种类，是预览、变更记录和操作日志共用的稳定码。

    Attributes:
        CREATE_LINK: create_link，建链（M1-08，L1-L4）。
        CREATE_DATASET: create_dataset，新增数据集（M1-08，L5、L6）。
        REPOINT_DATASET: repoint_dataset，改指向（M1-09，L17-L19）。
        SET_DATA_ORIGIN: set_data_origin，数据来源标注（M1-10，只改来源.json）。
        REVERT_CHANGE: revert_change，撤回某个已完成作业（L16，本票）。
    """

    CREATE_LINK = "create_link"
    CREATE_DATASET = "create_dataset"
    REPOINT_DATASET = "repoint_dataset"
    SET_DATA_ORIGIN = "set_data_origin"
    REVERT_CHANGE = "revert_change"


class FileImage(BaseModel):
    """一个普通文件在某一时刻的样子（前像或后像），不含正文。

    Attributes:
        model_config: 冻结，拒绝未知字段，不回显输入。
        exists: 文件是否存在；前像为 False 表示这一步新建文件。
        sha256: 存在时为 64 位小写十六进制（按原字节）；不存在时为 None。
        size_bytes: 存在时的字节数，≥ 0；不存在时为 None。
    """

    model_config = _FROZEN
    exists: bool
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)


class WriteFileStep(BaseModel):
    """把一个 JSON（或其他普通）文件原子替换成新内容。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        op: 固定 write_file，作判别字段。
        path: 相对 nav_root 的 POSIX 路径，非空，无 `..`，不经软链接。
        before: 计划时看到的前像；执行时在写锁下重读并核对相等，对不上以冲突失败。
        after: 后像（哈希与大小），由 after_content 的 UTF-8 字节算出。
        after_content: 要写入的完整新正文（UTF-8 文本），只存在于预览文件里；
            写入日志不抄这份正文，只记 after 的哈希。
    """

    model_config = _FROZEN
    op: Literal["write_file"] = "write_file"
    path: str = Field(min_length=1)
    before: FileImage
    after: FileImage
    after_content: str


class SetLinkStep(BaseModel):
    """创建软链接，或把已有软链接改指向新目标（先建临时名，再 rename 盖过去）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        op: 固定 set_link。
        path: 链接自己的位置，相对 nav_root，非空。
        before_target: 前像，即 os.readlink 的原样字符串；原来不存在为 None。
        after_target: 后像，新目标的绝对路径文本，非空。
    """

    model_config = _FROZEN
    op: Literal["set_link"] = "set_link"
    path: str = Field(min_length=1)
    before_target: str | None
    after_target: str = Field(min_length=1)


class MakeDirStep(BaseModel):
    """新建一个目录（前像是"不存在"）。回滚时仅当目录为空才删除。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        op: 固定 make_dir。
        path: 目录位置，相对 nav_root，非空；创建时其父目录必须已存在。
    """

    model_config = _FROZEN
    op: Literal["make_dir"] = "make_dir"
    path: str = Field(min_length=1)


class MovePathStep(BaseModel):
    """把一个目录、链接或文件改名挪到另一处（移除数据集用，ADR 0009 L7；本票只定义、不使用）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        op: 固定 move_path。
        path: 来源位置，相对 nav_root；前像是它存在、to_path 不存在。
        to_path: 目标位置，相对 nav_root，必须与 path 在同一文件系统；后像是它存在、path 不存在。
        entry_kind: 被挪对象的类型：目录、软链接或普通文件。
    """

    model_config = _FROZEN
    op: Literal["move_path"] = "move_path"
    path: str = Field(min_length=1)
    to_path: str = Field(min_length=1)
    entry_kind: Literal["directory", "symlink", "file"]


class RemovePathStep(BaseModel):
    """删除一个文件、软链接或空目录（撤回"新建"类操作时用；ADR 0009 L16）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        op: 固定 remove_path。
        path: 被删对象的位置，相对 nav_root，非空。
        entry_kind: 被删对象的类型：普通文件、软链接或目录。目录必须在执行时已是空的，
            里面的内容由排在它前面的删除步骤负责，所以本步骤从不递归删除。
        before_file: entry_kind 为 file 时的前像（哈希与大小，执行时核对）；其余 None。
        before_target: entry_kind 为 symlink 时的前像（readlink 原样）；其余 None。
    """

    model_config = _FROZEN
    op: Literal["remove_path"] = "remove_path"
    path: str = Field(min_length=1)
    entry_kind: Literal["file", "symlink", "directory"]
    before_file: FileImage | None = None
    before_target: str | None = None


type Step = Annotated[
    WriteFileStep | SetLinkStep | MakeDirStep | MovePathStep | RemovePathStep,
    Field(discriminator="op"),
]


class NewDatasetState(BaseModel):
    """新增数据集另记的两样预览状态（L12）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        destination_path: 预计新建的按任务入口，相对 nav_root。
        destination_absent: 预览时目的目录不存在。
        max_number: 预览时 `按任务/` 与 `已移除/` 里 dataset-N 的最大 N；一个都没有为 0。
            执行时在写锁下重算，不相等就以冲突失败（编号可能已被别的作业用掉）。
    """

    model_config = _FROZEN
    destination_path: str = Field(min_length=1)
    destination_absent: bool
    max_number: int = Field(ge=0)


class PreviewState(BaseModel):
    """预览时记下的状态（L12），执行前在写锁下重算并逐项核对。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        nav_root: 预览所用导航根的绝对路径文本；不同根的预览不能互用。
        datasets: 每个受影响数据集的第 01 张指纹（按任务入口及全部按格式入口，含来源.json 的哈希、
            条目名清单、每条链接的 readlink），按 dataset_id 升序；新增数据集时为空元组。
        new_dataset: 仅新增数据集时有值，其余为 None。
    """

    model_config = _FROZEN
    nav_root: str = Field(min_length=1)
    datasets: tuple[DatasetFingerprint, ...]
    new_dataset: NewDatasetState | None


class NavWritePlan(BaseModel):
    """一次写导航层的完整计划：预览、执行、写入日志、变更记录共用。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        operation: 操作种类。
        dataset_ids: 受影响的永久编号，升序、不重复；新增数据集是预计分配的编号。
        steps: 按执行顺序排列的步骤；回滚按相反顺序。顺序约束：先建目录，再写文件和链接，
            先写规范副本，再写按格式入口（ADR 0006）。
        state: 预览状态，供执行前核对。
        reverts_job_id: 仅撤回计划有值，被撤回的作业编号；其余为 None。
    """

    model_config = _FROZEN
    operation: NavOperation
    dataset_ids: tuple[str, ...]
    steps: tuple[Step, ...]
    state: PreviewState
    reverts_job_id: int | None = Field(default=None, ge=1)


class CheckScope(StrEnum):
    """预览里一项检查的范围（规范 2.4）：全量、抽样，还是执行之后才知道。

    Attributes:
        FULL: full，全量检查。
        SAMPLED: sampled，抽样检查，detail 写抽样口径。
        AFTER_EXECUTION: after_execution，预览时无法检查，要执行之后才知道。
    """

    FULL = "full"
    SAMPLED = "sampled"
    AFTER_EXECUTION = "after_execution"


class CheckNote(BaseModel):
    """一项检查及其范围。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        name: 检查名，中文，非空。
        scope: 检查范围。
        detail: 补充说明（抽样口径、为什么要执行后才知道），可为空串。
    """

    model_config = _FROZEN
    name: str = Field(min_length=1)
    scope: CheckScope
    detail: str


class FieldChangeCount(BaseModel):
    """按字段分组的改动数量（L18：预览按字段分组给数量）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        file: 相对 nav_root 的文件路径。
        field: 字段的 JSON 路径分组，例如 `links[].source_path`、`sources[].direct_path`。
        count: 该分组里要改的处数，≥ 1。
    """

    model_config = _FROZEN
    file: str = Field(min_length=1)
    field: str = Field(min_length=1)
    count: int = Field(ge=1)


class ListedChange(BaseModel):
    """需要逐处列出的改动（Markdown 正文与 notes 里的替换，L18）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        file: 相对 nav_root 的文件路径。
        json_path: 字符串值所在的 JSON 路径。
        before: 改前的片段，截取到上下文足够辨认，非空。
        after: 改后的片段，非空。
    """

    model_config = _FROZEN
    file: str = Field(min_length=1)
    json_path: str = Field(min_length=1)
    before: str
    after: str


class PreviewNotice(BaseModel):
    """预览里需要提醒用户的一条说明或拒绝理由，字段对应诊断的五段内容。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        code: 稳定的规则码，英文，例如 `will_add_dataset_root`、`source_not_reachable`。
        message: 中文说明，非空，不含口令等敏感信息。
        objects: 涉及的对象（路径、编号），键值对元组，可为空。
    """

    model_config = _FROZEN
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    objects: tuple[tuple[str, str], ...]


class PlanReport(BaseModel):
    """给人看的预览报告，由计划算出，不独立重算规则。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        file_count: 将写的文件数，≥ 0。
        link_count: 将建或改的链接数，≥ 0。
        directory_count: 将建的目录数，≥ 0。
        field_counts: 按文件和字段分组的数量，完整不截断。
        listed_changes: 逐处列出的改动，至多 PREVIEW_LISTED_CHANGE_LIMIT 条样例。
        listed_total: 应逐处列出的总数，≥ len(listed_changes)；总数始终完整。
        checks: 预览做了哪些检查及其范围。
        notices: 提醒与例外，例如"将把 X 加进 dataset_roots"、alpha 少 3 个数据块。
        creation: 建链和新增数据集的结构化差异；其他操作及历史预览为 None。
    """

    model_config = _FROZEN
    file_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    directory_count: int = Field(ge=0)
    field_counts: tuple[FieldChangeCount, ...]
    listed_changes: tuple[ListedChange, ...]
    listed_total: int = Field(ge=0)
    checks: tuple[CheckNote, ...]
    notices: tuple[PreviewNotice, ...]
    creation: CreationDetails | None = None


class NavPreview(BaseModel):
    """预览作业的结果，整体存成 `nav-previews/<预览作业编号>.json.gz`。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        format_version: 磁盘格式版本，固定 PREVIEW_FORMAT_VERSION。
        preview_job_id: 产生它的预览作业编号，≥ 1；写入作业靠它找到计划。
        created_at: 预览完成的 UTC 时刻（带时区）。
        parameters: 预览作业的参数原样回显（已校验、无秘密），供页面显示"你预览的是什么"。
        plan: 要执行的计划。
        report: 给人看的报告。
    """

    model_config = _FROZEN
    format_version: Literal[1] = 1
    preview_job_id: int = Field(ge=1)
    created_at: datetime
    parameters: dict[str, JsonValue]
    plan: NavWritePlan
    report: PlanReport


class ApplyResult(BaseModel):
    """一次写入作业的结果摘要，用于进度、作业日志结尾和操作日志，不是作业结果枚举。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        job_id: 写入作业编号，≥ 1；等于变更记录编号。
        operation: 操作种类。
        outcome: committed 已提交；rolled_back 中途失败并已退回；
            noop 预览状态核对通过但计划没有步骤（例如建链场景一"已经是这样了"），什么都没写。
        dataset_ids: 受影响的永久编号。
        file_count: 实际写入的文件数。
        link_count: 实际建或改的链接数。
        reindexed_dataset_ids: 已更新索引的数据集；回滚或 noop 时为空。
        sizing_job_ids: 随后提交的统计大小作业编号，每个数据集一个；回滚或 noop 时为空。
    """

    model_config = _FROZEN
    job_id: int = Field(ge=1)
    operation: NavOperation
    outcome: Literal["committed", "rolled_back", "noop"]
    dataset_ids: tuple[str, ...]
    file_count: int = Field(ge=0)
    link_count: int = Field(ge=0)
    reindexed_dataset_ids: tuple[str, ...]
    sizing_job_ids: tuple[int, ...]


class MismatchItem(BaseModel):
    """回滚时既不等于前像、也不等于后像的一项（L14：停下并列出）。

    Attributes:
        model_config: 冻结，拒绝未知字段。
        job_id: 该项所属的写入日志的作业编号，≥ 1。
        step_index: 在写入日志里的步骤序号，从 0 起。
        path: 相对 nav_root 的路径。
        expected_before: 前像的文字描述（哈希或链接目标或"不存在"），非空，不含文件正文。
        expected_after: 后像的文字描述，非空。
        actual: 磁盘现状的文字描述，非空；读不了时写原因而不是正文。
    """

    model_config = _FROZEN
    job_id: int = Field(ge=1)
    step_index: int = Field(ge=0)
    path: str = Field(min_length=1)
    expected_before: str = Field(min_length=1)
    expected_after: str = Field(min_length=1)
    actual: str = Field(min_length=1)
