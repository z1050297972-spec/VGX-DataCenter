"""导航层 JSON 的读入与写出规则（领域层，M1-07，ADR 0009 L10/L11）。

纯函数，不访问文件系统。用标准库 json：它保持键的插入顺序，不认识的键原样保留，
所以"保持原来的键顺序、新键追加在末尾"不需要自己写解析器。不负责决定改什么，
只负责把改完的对象写成约定的字节。
"""

from rdp.jobs.datasets.types import EntryLocation, JsonObject


def load_navigation_json(content: bytes) -> JsonObject:
    """把一份导航层 JSON 的原字节读成保持键顺序的对象。

    Args:
        content: 文件原字节，UTF-8，不含 BOM；长度不超过 MAX_DOCUMENT_BYTES。

    Returns:
        顶层 JSON 对象，键顺序与文件一致，未知键原样保留，数字保持 int/float 区别。

    Raises:
        InputError: 不是合法 UTF-8 JSON、顶层不是对象或超过大小上限；诊断写明文件无法读取的原因，不回显正文。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError


def dump_navigation_json(payload: JsonObject) -> bytes:
    """按 L11 把 JSON 对象写成字节：保持键顺序，2 空格缩进，中文不转义，结尾一个换行。

    Args:
        payload: 要写出的顶层对象；键顺序即输出顺序，新键应已追加在末尾。

    Returns:
        UTF-8 字节，`ensure_ascii=False`、`indent=2`，以单个换行符结尾。
        对一份没有被改动的文件，load 之后再 dump 的结果与原字节相同，除 L10 的推导字段外（验收 1 的原样写回对拍）。

    Raises:
        InputError: payload 含非有限浮点数或不可序列化的值。

    Side Effects:
        无。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError


def regenerate_derived_fields(payload: JsonObject, location: EntryLocation) -> JsonObject:
    """整组重新生成推导字段（L10），其余内容一字不动。

    Args:
        payload: 原始路径.json 或子任务.json 的内容；数据集信息.json 没有推导字段，不应传入。
        location: 该文件所在入口的位置，视图、格式、版本都从它取，不从 payload 里的旧值取。

    Returns:
        新对象：顶层 `view`、`format`、`version` 按位置重写（按任务入口为 `format: null`、`version: null`；
        按格式入口 `version` 省略时也显式写 `version: null`）；`links[].entry_path` 与
        `sources[].entry_path` 按 reading.derive_source_entry_path 重新推导。键已存在时留在原位，
        原来没有的键追加在末尾。不补 `schema_version`。

    Raises:
        InputError: payload 的 links 或 sources 结构不合法，或位置与 payload 的 dataset_id 无法对应。

    Side Effects:
        无；返回新对象，不改 payload。

    Time Semantics:
        同步纯函数，无时钟、无 I/O。
    """
    raise NotImplementedError
