"""假导航层的清单格式与展开边界（10、Q15），测试输入仅来自 tests/fixtures/nav。

清单由 samples 原件与 sources.tsv/layout.txt 的只读副本整理；真实文件不作为运行时输入。
使用已批准 pydantic 校验结构，pathlib/json 展开文件，不另造序列化器。
来源路径拆成从根开始的分量，仅供人工追溯，不作为文件访问目标；实际部署路径全部用占位符。
裁剪须按 dataset_id/source_id/task_key 成组选择，两个视图保留同一组身份并保留视图差异。
原件已有的失效引用通过 retained_missing_paths 显式保留，不能为了让夹具“干净”而修复历史事实。
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rdp.infra.config import StorageRootConfig

# 只构造极小占位内容；样本 JSON 单独从 sample_file 复制，不受占位文本的 1 KiB 上限影响。
MAX_PLACEHOLDER_BYTES = 1024
# 五个截短样本的总复制预算为 2 MiB，防止不小心把完整大 JSON 或数据文件纳入测试。
MAX_FIXTURE_SAMPLE_BYTES = 2 * 1024 * 1024
# 只替换完整根分量，LeRobot的帧/视频模板保持原样。
_ROOT_TOKEN = re.compile(r"\{(?:nav_root|dataset1|dataset2)\}(?=/|[\s`'\";，；。)]|$)")
# 两个视图外目录与空格式目录来自只读采集布局；不是数据集入口。
_REQUIRED_DIRECTORIES = frozenset(
    "{nav_root}/" + name
    for name in (
        "按格式/lerobot/2.0",
        "按格式/lerobot/2.1",
        "索引",
        "文档",
        "工具",
        "解压样本",
        "VGX_video",
    )
)
_TOKENS = frozenset({"{nav_root}", "{dataset1}", "{dataset2}"})
# 仅这三种是两份真实meta中的LeRobot模板，不作为根标记展开。
_DATA_TEMPLATES = frozenset({"chunk_index:03d", "file_index:03d", "video_key"})
_TEMPLATE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z_0-9]*(?::[^{}]+)?)\}")


class ManifestModel(BaseModel):
    """清单模型共用不可变、未知字段拒绝的规则；JSON 数组转换为元组。"""

    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


class FixtureRoot(ManifestModel):
    """临时根的登记，不使用本机 UUID。

    Attributes:
        name: dataset1 或 dataset2，展开为 tmp_path/roots/name；不接受任意目录。
        uuid: 合成的有效小写 UUID，仅供替换挂载表使用，不查询系统 UUID 目录。
        writable: 默认 False；夹具本身造数据不代表平台获得写许可。
    """

    name: Literal["dataset1", "dataset2"]
    uuid: str
    writable: bool = False


class SampleFile(ManifestModel):
    """一份截取 JSON 的来源与输出位置，原件哈希不等于截取后文件哈希。

    Attributes:
        sample_file: 相对 fixtures/nav 的普通 JSON 文件位置，不含 .. 或软链接跳出。
        destination: 以 {nav_root}、{dataset1} 或 {dataset2} 开头的输出位置。
        asset_path: 原件在 samples/ 下的相对路径，与 sources.tsv 第一列一致。
        source_path_parts: sources.tsv 第二列绝对来源路径的分量，省略开头根分隔符；
            拼接一个根分隔符即可无损恢复原路径，仅用于追溯，禁止用于 I/O。
        original_sha256: sources.tsv 的 64 位小写十六进制摘要，不重新计算原件身份。
        original_size_bytes: 原件字节数，正整数，来自 sources.tsv。
        truncation: 非空中文说明，逐项说明删了什么、为何删、如何维护引用；未截短明确写未截短。
    """

    sample_file: str
    destination: str
    asset_path: str
    source_path_parts: tuple[str, ...]
    original_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_size_bytes: int = Field(gt=0)
    truncation: str = Field(min_length=1)


class FixtureLink(ManifestModel):
    """入口内一条真实软链接，所有目标均落在临时根内。

    Attributes:
        name: 入口下单个名字，不含分隔符、NUL、. 或 ..，保留中文和特殊字符。
        target: 以根占位符开头的目标目录，必须在 directories 中声明，不允许导航层循环。
    """

    name: str
    target: str


class FixtureEntry(ManifestModel):
    """一个视图入口，JSON 的安装位置由 samples.destination 唯一指定。

    Attributes:
        dataset_id: 原件数据集编号，不重算。
        path: 相对 nav_root 的入口路径，必须在按任务或按格式内。
        links: 按 layout.txt 顺序的链接元组，允许跨盘、按子目录分别链接。
    """

    dataset_id: str
    path: str
    links: tuple[FixtureLink, ...]


class PlaceholderFile(ManifestModel):
    """用于表现目录形态的微型文本文件，不冒充视频、MCAP 或可解压压缩包。

    Attributes:
        destination: 根或导航层占位符开头的目标路径，不得覆盖样本 JSON 或链接。
        text: UTF-8 占位文本，最多 MAX_PLACEHOLDER_BYTES 字节，允许空文本。
    """

    destination: str
    text: str


class DatasetSelection(ManifestModel):
    """三份 JSON 与两个视图共用的截取身份清单。

    Attributes:
        dataset_id: 原始稳定编号。
        source_ids: 同一数据集两个视图保留的 source_id，顺序与规范副本相同，不重算。
        task_keys: 保留的 task_key；相关 shared_source_roots、task_metadata 一并裁剪。
        retained_missing_paths: 原件本就缺失、刻意不创建的占位符路径，保留 M1 异常检查输入。
        explanation: 非空中文，说明选择记录的理由、跨盘和难处理字符的覆盖、计数更新及历史差异。
    """

    dataset_id: str
    source_ids: tuple[str, ...]
    task_keys: tuple[str, ...]
    retained_missing_paths: tuple[str, ...]
    explanation: str = Field(min_length=1)


class NavManifest(ManifestModel):
    """tests/fixtures/nav/manifest.json 的唯一格式定义。

    Attributes:
        schema_version: 固定 1，不猜测未来版本。
        roots: 两个合成根，名字唯一。
        entries: 两个视图各五个入口，共十个，保留 layout.txt 的十八条链接。
        directories: 占位符开头的全部目标目录、空格式目录和非数据集目录结构；父目录可隐式创建。
        files: 小占位文件，含文档第一层的文件名；与 samples 目标互斥。
        samples: 三十份入口 JSON 加两份 meta/info.json，逐份记来源、哈希和截短说明。
        selections: 五个数据集的裁剪选择；保留中文标点、空格、括号、撇号。
    """

    schema_version: Literal[1]
    roots: tuple[FixtureRoot, ...]
    entries: tuple[FixtureEntry, ...]
    directories: tuple[str, ...]
    files: tuple[PlaceholderFile, ...]
    samples: tuple[SampleFile, ...]
    selections: tuple[DatasetSelection, ...]

    @model_validator(mode="after")
    def validate_layout(self) -> Self:
        """在写临时文件前核对清单形态与路径封闭性。

        Args:
            无。

        Returns:
            当前清单，根、入口、样本、选择的数量和身份配对符合 Attributes。

        Raises:
            ValueError: 数量/身份重复或缺失、来源记录不完整、占位符未知、路径含 NUL/..、
                绝对目标未使用占位符、文件/目录/链接目标冲突、目标不是已声明目录、
                缺少三种 JSON、两个 meta 样本、空格式目录或非数据集目录、占位文本超字节限制。

        Side Effects:
            无；只校验字符串和集合，不恢复来源路径做访问。

        Time Semantics:
            展开前完整校验，不取时钟，不依赖本机挂载状态。
        """
        _validate_counts(self)
        _validate_sources(self)
        _validate_paths(self)
        if any(len(file.text.encode("utf-8")) > MAX_PLACEHOLDER_BYTES for file in self.files):
            raise ValueError("占位文本超过字节上限")
        return self


@dataclass(frozen=True)
class FakeNavigation:
    """单个测试私有的导航层结果，不随会话共享可变目录。

    Attributes:
        nav_root: tmp_path 下已展开的导航层绝对路径。
        storage_roots: 两个可直接使用的 StorageRootConfig；各自 path 给出假根位置，按清单顺序。
        manifest: 已校验清单，供测试按来源和数据集身份定位样本。
    """

    nav_root: Path
    storage_roots: tuple[StorageRootConfig, ...]
    manifest: NavManifest


def expand_fake_nav(tmp_path: Path, *, fixture_dir: Path) -> FakeNavigation:
    """在测试私有临时目录中展开与真实布局同形的微型导航层。

    Args:
        tmp_path: pytest 提供的已存在空临时目录，绝对 Path；不能指向真实用户目录或数据挂载点。
        fixture_dir: 仓库内 tests/fixtures/nav 绝对路径，必填；只读 manifest.json 与登记的普通样本文件。

    Returns:
        FakeNavigation；nav_root 为 tmp_path/nav，根为 tmp_path/roots 下两个名字。
        三份 JSON 的保留记录在两个视图间对应，links 是真实绝对软链接，全部解析到假根内。
        meta/info.json 保留 franka/20/v3.0 与 null/30.0/v3.0，不制造另一种机器人标签。

    Raises:
        ValueError: 清单/样本 JSON 不合法、输入目录不符合约束、路径逃逸、含真实数据挂载前缀、
            未知或未替换根占位符、引用与选择不一致、样本总字节数超过 MAX_FIXTURE_SAMPLE_BYTES；
            写前预检，原有历史失效引用只允许 selections 明确列出的项。
        OSError: 读取样本、建临时目录、小文件或真实软链接失败；残留仅在 tmp_path 内。

    Side Effects:
        只写 tmp_path；不改夹具源文件、不读规划目录，不使用 source_path_parts 打开原件。
        用完整路径分量识别根占位符，对 JSON 键和值及 Markdown 内路径替换；
        不误替换同前缀名字，不把 meta 中 {video_key} 等 LeRobot 模板当作根占位符。
        创建空的按格式/lerobot/2.0、2.1 与索引、文档、工具、解压样本、VGX_video 的第一层；
        不复制数据载荷，失败现场由 pytest 临时目录保留策略管理。

    Time Semantics:
        每个测试重新展开，不使用文件 mtime 判断新旧，不访问系统时钟或挂载表。
    """
    _validate_input_directories(tmp_path, fixture_dir)
    manifest = NavManifest.model_validate_json(
        (fixture_dir / "manifest.json").read_text(encoding="utf-8")
    )
    locations = {
        "{nav_root}": tmp_path / "nav",
        **{"{" + root.name + "}": tmp_path / "roots" / root.name for root in manifest.roots},
    }
    payloads = _read_samples(manifest, fixture_dir, locations)
    for path in locations.values():
        path.mkdir(parents=True)
    for directory in manifest.directories:
        _destination(directory, locations).mkdir(parents=True, exist_ok=True)
    for file in manifest.files:
        destination = _destination(file.destination, locations)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(file.text, encoding="utf-8")
    for destination, content in payloads:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
    for entry in manifest.entries:
        directory = locations["{nav_root}"] / entry.path
        directory.mkdir(parents=True, exist_ok=True)
        for link in entry.links:
            (directory / link.name).symlink_to(
                _destination(link.target, locations), target_is_directory=True
            )
    return FakeNavigation(
        locations["{nav_root}"],
        tuple(
            StorageRootConfig(
                name=root.name,
                path=locations["{" + root.name + "}"],
                uuid=root.uuid,
                writable=root.writable,
            )
            for root in manifest.roots
        ),
        manifest,
    )


def _destination(value: str, locations: dict[str, Path]) -> Path:
    """目标用完整首分量选择临时根，不进行字符串前缀猜测。"""
    token, *parts = value.split("/")
    if token not in locations or any(part in {"", ".", ".."} or "\x00" in part for part in parts):
        raise ValueError("目标不是合法根占位符路径")
    return locations[token].joinpath(*parts)


def _validate_input_directories(target: Path, source: Path) -> None:
    """禁止把真实数据位置或已有目录当作可覆盖的测试输出。"""
    for path in (target, source):
        if not path.is_absolute() or ".." in path.parts or "\x00" in str(path):
            raise ValueError("输入目录须为无穿越的绝对路径")
    if len(target.parts) < 3 or target.parts[1] in {"mnt", "home", "root"}:
        raise ValueError("输出必须是测试私有临时目录")
    if target.resolve() != target or not target.is_dir() or any(target.iterdir()):
        raise ValueError("输出目录须存在、为空且不能是软链接")
    if ".scratch" in source.parts or target.is_relative_to(source) or source.is_relative_to(target):
        raise ValueError("样本源与输出须隔离，不能从规划目录读样本")


def _replace_paths(value: object, locations: dict[str, Path]) -> object:
    """递归处理键、值与Markdown文本，不解析或改写数据自己的格式模板。"""
    if isinstance(value, str):
        if "/" + "mnt/" in value:
            raise ValueError("样本含真实数据挂载前缀")
        result = _ROOT_TOKEN.sub(lambda match: str(locations[match[0]]), value)
        if any(token not in _DATA_TEMPLATES for token in _TEMPLATE_PATTERN.findall(result)):
            raise ValueError("样本含未知或未展开根占位符")
        return result
    if isinstance(value, list):
        return [_replace_paths(item, locations) for item in cast(list[object], value)]
    if isinstance(value, dict):
        return {
            str(_replace_paths(key, locations)): _replace_paths(item, locations)
            for key, item in cast(dict[str, object], value).items()
        }
    return value


def _validate_counts(manifest: NavManifest) -> None:
    """数量和身份对应采集的两个视图五个样本，不能用重复项填足数量。"""
    if len(manifest.roots) != 2 or {root.name for root in manifest.roots} != {
        "dataset1",
        "dataset2",
    }:
        raise ValueError("必须恰有两个不同假存储根")
    if len(manifest.entries) != 10 or len({entry.path for entry in manifest.entries}) != 10:
        raise ValueError("两个视图必须各有五个唯一入口")
    if len(manifest.selections) != 5 or len({item.dataset_id for item in manifest.selections}) != 5:
        raise ValueError("必须有五个不同数据集的裁剪选择")
    for selection in manifest.selections:
        views = [
            entry.path.split("/")[0]
            for entry in manifest.entries
            if entry.dataset_id == selection.dataset_id
        ]
        if sorted(views) != ["按任务", "按格式"]:
            raise ValueError("每个数据集必须在两个视图配对")
    if (
        len(manifest.samples) != 32
        or len({sample.sample_file for sample in manifest.samples}) != 32
    ):
        raise ValueError("必须有32份不同样本")


def _validate_sources(manifest: NavManifest) -> None:
    """来源按路径分量保存，只做文字追溯校验，不用它打开真实原件。"""
    for sample in manifest.samples:
        _relative(sample.sample_file)
        _relative(sample.asset_path)
        parts = sample.asset_path.split("/")
        origin = sample.source_path_parts
        if not origin or origin[0] != "mnt" or len(origin) < 3:
            raise ValueError("来源路径分量不完整")
        expected = ("datasets", *parts[1:]) if parts[0] == "nav" else tuple(parts[1:])
        if origin[1:] != expected or sample.sample_file != "samples/" + sample.asset_path:
            raise ValueError("来源与样本相对路径不一致")


def _relative(value: str) -> None:
    """清单中的相对位置必须能逐段安全拼接，不能靠resolve补救穿越。"""
    if not value or any(part in {"", ".", ".."} or "\x00" in part for part in value.split("/")):
        raise ValueError("清单路径不是合法相对路径")


def _validate_paths(manifest: NavManifest) -> None:
    """全部写入目标在创建目录前去重并核对祖先，禁止透过清单链接写文件。"""
    locations = {token: Path("/") / token for token in _TOKENS}
    directories = set(manifest.directories)
    leaves = [item.destination for item in manifest.samples] + [
        item.destination for item in manifest.files
    ]
    if not directories >= _REQUIRED_DIRECTORIES or len(directories) != len(manifest.directories):
        raise ValueError("缺少空格式/非数据集目录或目录重复")
    for entry in manifest.entries:
        _relative(entry.path)
        directories.add("{nav_root}/" + entry.path)
        for link in entry.links:
            _relative(link.name)
            if (
                "/" in link.name
                or link.target not in directories
                or link.target.startswith("{nav_root}")
            ):
                raise ValueError("链接须指向已声明的假存储目录")
            leaves.append("{nav_root}/" + entry.path + "/" + link.name)
    if sum(len(entry.links) for entry in manifest.entries) != 18:
        raise ValueError("必须保留十八条链接")
    if len(set(leaves)) != len(leaves) or directories.intersection(leaves):
        raise ValueError("文件、目录或链接目标冲突")
    for value in (*directories, *leaves):
        _destination(value, locations)
    for leaf in leaves:
        if any(
            other != leaf and PurePosixPath(other).is_relative_to(leaf)
            for other in (*directories, *leaves)
        ):
            raise ValueError("文件或链接不能作为其他写入目标的祖先")


def _read_samples(
    manifest: NavManifest, fixture_dir: Path, locations: dict[str, Path]
) -> list[tuple[Path, str]]:
    """先完整读取和校验，任何样本失败都不得留下已展开的半份目录。"""
    result: list[tuple[Path, str]] = []
    documents: dict[str, dict[str, Any]] = {}
    total = 0
    for sample in manifest.samples:
        path = fixture_dir / sample.sample_file
        if not path.resolve(strict=True).is_relative_to(fixture_dir.resolve(strict=True)):
            raise ValueError("样本软链接越出夹具目录")
        if total + path.stat().st_size > MAX_FIXTURE_SAMPLE_BYTES:
            raise ValueError("样本总字节数超过预算")
        text = path.read_text(encoding="utf-8")
        total += len(text.encode("utf-8"))
        if total > MAX_FIXTURE_SAMPLE_BYTES:
            raise ValueError("样本总字节数超过预算")
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("样本须为JSON对象")
        documents[sample.destination] = cast(dict[str, Any], data)
        content = (
            json.dumps(
                _replace_paths(cast(dict[str, object], data), locations),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        result.append((_destination(sample.destination, locations), content))
    _validate_references(manifest, documents)
    return result


def _validate_references(manifest: NavManifest, documents: dict[str, dict[str, Any]]) -> None:
    """源编号和任务编号由清单选择，不能通过独立裁剪制造悬空引用。"""
    selections = {item.dataset_id: item for item in manifest.selections}
    try:
        for entry in manifest.entries:
            selected = selections[entry.dataset_id]
            prefix = "{nav_root}/" + entry.path + "/"
            paths, tasks, info = (
                documents[prefix + name]
                for name in ("原始路径.json", "子任务.json", "数据集信息.json")
            )
            if any(item["dataset_id"] != entry.dataset_id for item in (paths, tasks, info)):
                raise ValueError("入口的三份JSON身份不一致")
            if tuple(item["source_id"] for item in paths["sources"]) != selected.source_ids:
                raise ValueError("数据块选择不一致")
            if tuple(item["task_key"] for item in tasks["tasks"]) != selected.task_keys or tasks[
                "task_count"
            ] != len(selected.task_keys):
                raise ValueError("任务选择或计数不一致")
            if any(
                source["source_id"] not in selected.source_ids
                for task in tasks["tasks"]
                for source in task["sources"]
            ):
                raise ValueError("任务引用未选择的数据块")
    except (KeyError, TypeError) as error:
        raise ValueError("样本缺少合法配对与引用字段") from error
