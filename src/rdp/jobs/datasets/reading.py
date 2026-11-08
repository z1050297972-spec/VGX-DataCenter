"""导航读取与纯解析（领域层，M1-01、11 Q6/Q8），不写导航，不读取链接目标。

目录/文件使用 os.scandir、os.readlink、带 O_NOFOLLOW 的目录相对打开；JSON 用标准库 json。
项目特有的字段投影和路径推导由本模块维护，不能用严格新 schema 拒绝已有未知字段。
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import cast

from rdp.collection.information import read_collection
from rdp.infra.diagnostics import InputError
from rdp.jobs.datasets import _io, _json
from rdp.jobs.datasets._discovery import discover
from rdp.jobs.datasets._issues import external_error, finding, input_error
from rdp.jobs.datasets.catalog import MAX_DOCUMENT_BYTES, REQUIRED_DOCUMENTS
from rdp.jobs.datasets.origins import ORIGIN_CODES
from rdp.jobs.datasets.types import (
    EntryLocation,
    EntrySnapshot,
    JsonDocument,
    JsonObject,
    Link,
    NavigationCatalog,
    ProvenanceState,
    Source,
)
from rdp.jobs.navwrite.provenance import read_provenance


def discover_entries(nav_root: Path) -> NavigationCatalog:
    """枚举登记视图的全部入口，并报告未知顶层项和格式目录。

    Args:
        nav_root: 注入的绝对导航目录，路径分量不得为软链接，必须已存在。

    Returns:
        路径升序的 NavigationCatalog；lerobot 多一层版本目录，空版本目录不产生入口。
        非数据集登记目录只识别名字，完全不进入；未知顶层文件或目录均产生需要处理发现。
        顶层、视图、格式、版本或入口层的软链接不跟随，记录 NAV_UNSAFE_DIRECTORY。

    Raises:
        InputError: 根非绝对路径、含 ..、项数超过 MAX_SCAN_ENTRIES 或目录结构不安全。
        ExternalError: 根/必需视图或已登记视图目录无法枚举，不能把读取失败当空导航。

    Side Effects:
        无（只读导航目录本身；不扫描存储根，不修改登记表或目录）。

    Time Semantics:
        同步一次枚举，不等待目录出现、不重试；worker 第一段持写锁调用，Web只读调用允许观察漂移。
    """
    return discover(nav_root)


def parse_document(location: EntryLocation, name: str, content: bytes) -> JsonDocument:
    """按已有宽松读取契约解析一份导航 JSON，保留未知字段和原始摘要。

    Args:
        location: 已按目录位置确定的入口。
        name: REQUIRED_DOCUMENTS 中一项，不接受来源.json。
        content: 原始 UTF-8 JSON 字节，长度不超过 MAX_DOCUMENT_BYTES，允许零字节但会报解析发现。

    Returns:
        可用对象或 payload=None 加需要处理诊断；缺 schema_version 当1，不把该键写回原对象。
        未知版本（包括bool）、非法 UTF-8/JSON、非有限JSON数值、非对象、缺依赖字段或类型错误使整份不可用。
        原始路径依赖 dataset_id/name/roots、links 的 name/source_path/source_type、
        sources 的 source_id/original_path/direct_path；信息依赖 dataset_id 和 fields 的
        number/name/value_markdown 结构；子任务只依赖 schema_version/dataset_id。
        未知字段原样保留；省略 version 与 null 的等价只作用于投影和比较，不改变 payload。

    Raises:
        InputError: name 不受支持、位置形状错误或字节数越界；坏 JSON 本身以发现返回。

    Side Effects:
        无；纯解析及 hashlib 原字节哈希，不查任何路径是否存在，不记录整份载荷。

    Time Semantics:
        不取时钟，相同字节及位置产生相同解析结果；不使用文件修改时刻推测内容。
    """
    if name not in REQUIRED_DOCUMENTS or len(content) > MAX_DOCUMENT_BYTES:
        problem = input_error(str(location.path), "文件名或字节数不符合读取范围")
        raise problem
    digest = hashlib.sha256(content).hexdigest()
    try:
        payload = _json.object_value(
            json.loads(
                content.decode("utf-8"),
                parse_float=_json.finite_number,
                parse_constant=_json.finite_number,
            )
        )
    except (ValueError, UnicodeError, RecursionError):
        issue = finding(str(location.path), "JSON_INVALID", f"{name}：无法解析UTF-8 JSON对象")
        return JsonDocument(name, None, digest, None, (issue,))
    version = payload.get("schema_version", 1)
    if type(version) is not int or version != 1:
        issue = finding(
            str(location.path), "JSON_SCHEMA_VERSION", f"{name}：schema_version不受支持"
        )
        return JsonDocument(name, None, digest, None, (issue,))
    try:
        _json.validate(payload, name)
    except ValueError as error:
        issue = finding(
            str(location.path), "JSON_REQUIRED_FIELD", f"{name}：字段{error}缺失或类型错误"
        )
        return JsonDocument(name, None, digest, None, (issue,))
    return JsonDocument(name, payload, digest, 1, ())


def read_entry(
    nav_root: Path, location: EntryLocation, *, checkpoint: Callable[[], None]
) -> EntrySnapshot:
    """读取一个入口的三份 JSON 并投影有效字段，坏文件仍保留入口身份。

    Args:
        nav_root: 绝对导航根，所有路径分量必须是普通目录。
        location: discover_entries 返回的位置，不得逃逸 nav_root。
        checkpoint: 每文件/读块边界调用的控制检查点，不能省略。

    Returns:
        EntrySnapshot，三份文件缺失、打不开、非普通文件或 parse_document 拒绝时逐份记录发现。
        一份失败不丢弃其余文件；全部失败仍返回按目录名可展示的入口，dataset_id=None。
        links/source.entry_path 由位置推导，JSON 原值留给面板核对；来源.json 读取三态，
        其中数据来源字段忽略；来源筛选编码只读信息顶层，缺失或非法为 unknown。
        第4项原文保留但不解析，recorded_size_bytes 固定为 None。
        scene/tasks/robot_model 只投影信息文件顶层，不解析 Markdown；空值按未标注，自定义文本保留。
        collection 缺键或 null 为无采集信息；格式非法局部降级并产生 COLLECTION_INVALID 提示。

    Raises:
        InputError: location 越界、目录项数量超过 MAX_ENTRY_MEMBERS 或调用参数非法。
        ExternalError: 入口目录本身无法枚举；调用扫描器保留目录占位并计失败入口。
        JobCancelledError: 检查点在非锁保护区收到取消。
        WorkerStoppingError: 检查点在非锁保护区收到停止。

    Side Effects:
        无（只读取导航层普通文件和链接自身，O_NOFOLLOW 防止 JSON 软链接指向存储根）。
        单文件超过 MAX_DOCUMENT_BYTES 按该文件不可用诊断返回，不无限分配内存。

    Time Semantics:
        worker 持导航锁调用；每文件单次尝试，文件在读取期间消失也按不可用返回，无重试。
    """
    _validate_location(location)
    try:
        with _io.directory(nav_root / location.path) as descriptor:
            names = _io.names(descriptor)
            documents = tuple(
                _read_document(descriptor, location, name, checkpoint)
                for name in REQUIRED_DOCUMENTS
            )
    except OSError as error:
        problem = external_error(str(location.path), "入口目录无法枚举")
        raise problem from error
    manifest = documents[0].payload
    links = _links(location, manifest) if manifest is not None else ()
    sources = _sources(location, manifest, links) if manifest is not None else ()
    identity = next(
        (str(doc.payload["dataset_id"]) for doc in documents if doc.payload is not None), None
    )
    issues = tuple(issue for doc in documents for issue in doc.findings)
    roots = (
        tuple(str(value) for value in cast(list[object], manifest["dataset_roots"]))
        if manifest
        else ()
    )
    provenance = read_provenance(nav_root / location.path) if "来源.json" in names else None
    information = documents[1].payload or {}
    raw_origin = information.get("data_origin")
    origin = ORIGIN_CODES.get(raw_origin, "unknown") if isinstance(raw_origin, str) else "unknown"
    collection = read_collection(information.get("collection"))
    if information.get("collection") is not None and collection is None:
        issues += (
            finding(
                str(location.path),
                "COLLECTION_INVALID",
                "collection 格式非法，按无采集信息处理",
                notice=True,
            ),
        )
    raw_fps = information.get("fps")
    fps = raw_fps if type(raw_fps) is int and raw_fps > 0 else None
    return EntrySnapshot(
        location,
        documents,
        identity,
        roots,
        links,
        sources,
        "来源.json" in names,
        None,
        issues,
        provenance.state if provenance else ProvenanceState.ABSENT,
        origin,
        *classification(documents[1]),
        fps,
        collection,
    )


def derive_source_entry_path(
    location: EntryLocation, direct_path: str, links: tuple[Link, ...]
) -> str:
    """由已声明链接推导数据块入口路径，保留链接够不着的数据块绝对路径。

    Args:
        location: 来源入口的已验证位置。
        direct_path: 非空绝对路径文本，不检查磁盘存在性。
        links: 同入口声明的链接元组，空集合合法，顺序为 JSON 顺序。

    Returns:
        覆盖 direct_path 的最长完整路径分量前缀对应的导航路径；相同长度按链接名排序选首个。
        无覆盖时原样返回 direct_path（alpha 的历史失效数据块）；相似字符串前缀不算覆盖。

    Raises:
        InputError: 位置或声明路径非绝对、包含 NUL，或 links 不属于此入口。

    Side Effects:
        无；只计算字符串分量，不调用 resolve/exists，不修正 original_path。

    Time Semantics:
        纯函数，无时间输入；输入来自同一次入口读取，不混用两个视图的链接集合。
    """
    if not PurePosixPath(direct_path).is_absolute() or "\x00" in direct_path:
        problem = input_error(str(location.path), "数据块当前位置必须是绝对路径")
        raise problem
    for link in links:
        if not PurePosixPath(link.source_path).is_absolute() or link.entry_path != str(
            location.path / link.name
        ):
            problem = input_error(str(location.path), "链接不属于入口或目标不是绝对路径")
            raise problem
    matches = [
        link
        for link in links
        if PurePosixPath(direct_path).is_relative_to(PurePosixPath(link.source_path))
    ]
    if not matches:
        return direct_path
    link = sorted(
        matches, key=lambda item: (-len(PurePosixPath(item.source_path).parts), item.name)
    )[0]
    relative = PurePosixPath(direct_path).relative_to(link.source_path)
    return str(PurePosixPath(link.entry_path) / relative)


def classification(
    information: JsonDocument,
) -> tuple[tuple[str, ...], tuple[str, ...], str | None]:
    """从数据集信息顶层取场景、任务和机器人型号三个人工分类字段（M1.5-03）。

    Args:
        information: 数据集信息.json 的读取结果，payload=None 表示不可用。

    Returns:
        (scene, tasks, robot_model)：scene 兼容旧字符串，去空格、去空项、去重保序；
        缺失或无有效场景为空元组。robot_model 是去首尾空白后的非空文本，缺失、空串、非文本为 None；
        tasks 是数组里的非空文本项，去重并保持原顺序，缺失或不是数组为空元组。
        词表是推荐值，可以自定义；自定义值保留且不产生词表提示，tasks 不去除首尾空白，不读取 14 项 Markdown。

    Raises:
        无。

    Side Effects:
        无；只读已解析对象。

    Time Semantics:
        不取时钟；值属于本次读取的导航层内容。
    """
    payload = information.payload
    if payload is None:
        return (), (), None
    raw_tasks = payload.get("tasks")
    tasks = (
        tuple(
            dict.fromkeys(
                item for item in cast(list[object], raw_tasks) if isinstance(item, str) and item
            )
        )
        if isinstance(raw_tasks, list)
        else ()
    )
    return scene_values(payload.get("scene")), tasks, _text_or_none(payload.get("robot_model"))


def scene_values(value: object) -> tuple[str, ...]:
    """将导航层的新旧场景值统一为有序文本集合。

    Args:
        value: scene 原值；接受旧字符串或字符串数组，无单位。

    Returns:
        去首尾空格、去空项、去重保序的元组；缺失、null 或非文本值按未标注处理。

    Raises:
        无。

    Side Effects:
        无；不修改输入。

    Time Semantics:
        不取时钟，只反映传入快照。
    """
    values: list[object] = (
        [value]
        if isinstance(value, str)
        else cast(list[object], value)
        if isinstance(value, list)
        else []
    )
    return tuple(
        dict.fromkeys(item.strip() for item in values if isinstance(item, str) and item.strip())
    )


def _text_or_none(value: object) -> str | None:
    """分类字段只接受非空文本，其余按未填写处理。"""
    return value.strip() if isinstance(value, str) and value.strip() else None


def _validate_location(location: EntryLocation) -> None:
    """位置是目录发现的输出，仍拒绝调用方传入绝对路径或穿越。"""
    if (
        location.path.is_absolute()
        or ".." in location.path.parts
        or not location.path.parts
        or location.path.parts[0] not in {"按任务", "按格式"}
    ):
        problem = input_error(str(location.path), "入口位置越界")
        raise problem


def _read_document(
    descriptor: int, location: EntryLocation, name: str, checkpoint: Callable[[], None]
) -> JsonDocument:
    """文件故障局部降级，取消与停止不被OSError处理吞掉。"""
    try:
        return parse_document(location, name, _io.read_file(descriptor, name, checkpoint))
    except (OSError, InputError) as error:
        issue = finding(
            str(location.path),
            "JSON_UNREADABLE",
            f"{name}：无法读取普通文件（{type(error).__name__}）",
        )
        return JsonDocument(name, None, None, None, (issue,))


def _links(location: EntryLocation, manifest: JsonObject) -> tuple[Link, ...]:
    """推导路径单独保存，原payload保持未知字段与原始位置值。"""
    return tuple(
        Link(
            str(item["name"]),
            str(item["source_path"]),
            str(item["source_type"]),
            str(location.path / str(item["name"])),
        )
        for item in _json.objects(manifest["links"], "links")
    )


def _optional_text(item: JsonObject, key: str) -> str | None:
    """展示字段的结构不纳入读取依赖，非文本原值只留在payload。"""
    value = item.get(key)
    return value if isinstance(value, str) else None


def _sources(
    location: EntryLocation, manifest: JsonObject, links: tuple[Link, ...]
) -> tuple[Source, ...]:
    """按原顺序投影数据块，重复source_id也保留，不重算首次登记身份。"""
    return tuple(
        Source(
            str(item["source_id"]),
            str(item["original_path"]),
            str(item["direct_path"]),
            derive_source_entry_path(location, str(item["direct_path"]), links),
            _optional_text(item, "format"),
            _optional_text(item, "version"),
            _optional_text(item, "validation_status"),
        )
        for item in _json.objects(manifest["sources"], "sources")
    )
