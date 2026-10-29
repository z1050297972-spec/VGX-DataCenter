"""L12 数据集状态指纹（领域层，M1-01），供扫描提交和写入预览共同使用。

用 os.scandir/readlink 观察导航项、hashlib 流式哈希原字节；不 resolve、不 stat 链接目标。
冻结 Pydantic 值对象只含标量和元组，可比较相等，以 model_dump_json/model_validate_json 存取。
文件读取使用目录描述符及 O_NOFOLLOW，避免检查后替换成软链接时越界读取存储根。
"""

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileState(StrEnum):
    """缺失可以可靠比较；不可读或非普通文件不能证明内容未变。"""

    PRESENT = "present"
    MISSING = "missing"
    UNREADABLE = "unreadable"
    NOT_REGULAR = "not_regular"


class JsonFingerprint(BaseModel):
    """入口中一份 JSON 的原字节状态。

    Attributes:
        model_config: 冻结且拒绝未知字段，避免持久化版本被悄悄忽略。
        name: 单层 .json 文件名，非空；包括三份必需文件和来源.json，即使它们缺失。
        state: present/missing/unreadable/not_regular。
        sha256: present 时为64位小写摘要；其他状态为 None，不哈希异常消息。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    name: str = Field(min_length=1)
    state: FileState
    sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")


class LinkFingerprint(BaseModel):
    """一条实际软链接的字面目标，包含断链且不跟随目标。

    Attributes:
        model_config: 冻结且拒绝未知字段。
        name: 入口里的单层链接名，非空。
        target: os.readlink 原样字符串，保留相对路径和 ..；读不了为 None。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    name: str = Field(min_length=1)
    target: str | None


class EntryFingerprint(BaseModel):
    """入口本身及直接子项的快照，不递归普通子目录。

    Attributes:
        model_config: 冻结且拒绝未知字段。
        path: 相对导航根的入口路径，非空，无 ..。
        state: present 表示目录可枚举；missing 表示已删除；其他状态不可验证。
        names: 直接子项名字的完整 Unicode 升序元组，包含隐藏项，空目录为空。
        json_files: 按名字升序；必需四文件缺失也显式记录，额外 .json 同样哈希。
        links: 按名字升序的所有实际软链接；含以 .json 命名的链接但不读取其目标。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    path: str = Field(min_length=1)
    state: FileState
    names: tuple[str, ...]
    json_files: tuple[JsonFingerprint, ...]
    links: tuple[LinkFingerprint, ...]


class DatasetFingerprint(BaseModel):
    """可持久化且深度不可变的数据集导航状态；不含时间或存储根状态。

    Attributes:
        model_config: 冻结且拒绝未知字段，嵌套对象也冻结。
        schema_version: 指纹编码版本，固定1，与导航 JSON schema_version 无关。
        nav_root: 注入导航根的绝对路径文本，不 resolve；防止不同根的预览互用。
        dataset_id: 原编号；只能按损坏入口位置观察时为 None，不产生临时永久编号。
        entries: 按相对路径升序，包含按任务及全部按格式入口和 known_entry_paths 的缺失标记。
        verifiable: 所有目录/文件/链接都可观察且两次目录枚举一致才为 True。
            False 的两个值即使相等，也不能用于授权更新或证明预览未变。
    """

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    schema_version: Literal[1] = 1
    nav_root: str = Field(min_length=1)
    dataset_id: str | None
    entries: tuple[EntryFingerprint, ...]
    verifiable: bool


def fingerprint_dataset(
    nav_root: Path,
    dataset_id: str | None,
    *,
    known_entry_paths: tuple[str, ...],
    checkpoint: Callable[[], None],
) -> DatasetFingerprint:
    """采集数据集全部入口的 L12 指纹，重新发现入口集合以检出新增、删除和改身份。

    Args:
        nav_root: 已配置的绝对真实目录，路径分量不得是软链接；不使用默认部署路径。
        dataset_id: 非空永久编号；None 只用于完全无法识别身份的入口。
        known_entry_paths: 首次观察可为空；复核必须传上次全部入口路径，去重且不含 ..。
            dataset_id 为 None 时必须恰好一个入口，不按同名目录猜跨视图关联。
        checkpoint: 必填的有界检查点；由作业传取消/停止检查，锁内由框架延后控制异常。

    Returns:
        新 DatasetFingerprint：已知路径与当前所有声明该编号的入口的并集，路径升序。
        某入口任一可解析 JSON 声明该编号即纳入，不能因三份身份冲突遗漏入口。
        JSON 哈希按原字节，连空白改变也检出；readlink 原样保存，mtime 不参与比较。
        缺文件/缺入口用 missing；权限拒绝、扫描中变化或不安全文件用 verifiable=False，
        不伪造哈希。来源.json 无论存在与否均占一项；不解析它的内容。

    Raises:
        InputError: 路径/编号不合约、known_entry_paths 逃逸、扫描总预算超 MAX_SCAN_BYTES/ENTRIES。
        ExternalError: nav_root 或视图无法枚举，无法确定完整数据集入口集合。
        JobCancelledError: 非保护段的 checkpoint 检出人为取消。
        WorkerStoppingError: 非保护段的 checkpoint 检出 worker 停止。

    Side Effects:
        无（只读导航目录、普通 JSON 原字节和软链接自身，不访问链接目标、不写导航或索引）。
        每份 JSON 分块哈希，目录项上界为 MAX_ENTRY_MEMBERS；打不开单项返回不可验证值。

    Time Semantics:
        扫描第一段与提交复核在同一 worker 写锁下调用；写入预览可不持锁，执行前须持锁再算。
        检查点在每个文件和读块之间调用；不重试。外部手工写不受锁控制，检测到变化即不可验证，
        不能宣称多文件原子快照；不读取墙钟，不把两个不可验证值当作“未改变”。
    """
    from rdp.jobs.datasets import _fingerprints

    observed = _fingerprints.collect(nav_root, checkpoint)
    return _fingerprints.select(nav_root, dataset_id, known_entry_paths, observed, checkpoint)
