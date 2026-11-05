"""创建预览的内存计划装配（领域层，M1-08）。

复用第 07 张副本生成与 JSON 编码；不执行任何写步骤，标准库负责复制和哈希。
"""

import copy
import hashlib
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import cast

from rdp.jobs.datasets import _io
from rdp.jobs.datasets.catalog import FORMAT_DIRECTORIES, REQUIRED_DOCUMENTS
from rdp.jobs.datasets.reading import parse_document
from rdp.jobs.datasets.types import EntryLocation, EntrySnapshot, JsonObject, View
from rdp.jobs.navwrite._create_read import Target, present
from rdp.jobs.navwrite.create_details import CreationDetails, LinkAddition, SourceAddition
from rdp.jobs.navwrite.create_models import DatasetInformation, FirstLink, FormatEntrySelection
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jsonio import dump_navigation_json
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    FieldChangeCount,
    FileImage,
    MakeDirStep,
    NavWritePlan,
    PlanReport,
    PreviewNotice,
    SetLinkStep,
    Step,
    WriteFileStep,
)
from rdp.jobs.navwrite.replica import generate_format_entry

_RULE = "NAV_CREATE"


def under(path: str, parent: str) -> bool:
    """按路径分量判断覆盖关系，避免 b 误伤 bc。"""
    return path == parent or path.startswith(parent.rstrip("/") + "/")


def format_locations(
    name: str, selections: tuple[FormatEntrySelection, ...]
) -> tuple[EntryLocation, ...]:
    """用唯一登记表推导勾选入口，不接受自由磁盘路径。"""
    keys = [(item.format, item.version) for item in selections]
    if len(keys) != len(set(keys)):
        raise nav_input_error(_RULE, "格式入口选择不能重复")
    result: list[EntryLocation] = []
    for item in selections:
        definition = next(value for value in FORMAT_DIRECTORIES if value.format == item.format)
        path = PurePosixPath("按格式", definition.directory)
        if item.version is not None:
            path /= item.version
        result.append(EntryLocation(path / name, View.FORMAT, item.format, item.version, name))
    return tuple(sorted(result, key=lambda value: str(value.path)))


def payload(snapshot: EntrySnapshot, index: int) -> JsonObject:
    """只接受已有解析器确认可用的文档，保留未知键的插入顺序。"""
    value = snapshot.documents[index].payload
    if value is None:
        raise nav_input_error(_RULE, "规范副本 JSON 不可用")
    return copy.deepcopy(value)


def image(raw: bytes | None) -> FileImage:
    """依据原字节生成第 07 张文件像，不按重编码文本计算前像。"""
    return (
        FileImage(exists=False)
        if raw is None
        else FileImage(exists=True, sha256=hashlib.sha256(raw).hexdigest(), size_bytes=len(raw))
    )


def with_documents(snapshot: EntrySnapshot, files: tuple[bytes, ...]) -> EntrySnapshot:
    """以新文档替换快照正文，供同一份副本生成规则使用。"""
    docs = tuple(
        parse_document(snapshot.location, name, raw)
        for name, raw in zip(REQUIRED_DOCUMENTS, files, strict=True)
    )
    if any(item.payload is None for item in docs):
        raise nav_input_error(_RULE, "生成的导航 JSON 不满足读取契约")
    return replace(snapshot, documents=docs)


class Planning:
    """一个计划的步骤与报告累积器，只存在于一次 builder 调用。"""

    def __init__(self, root: Path, canonical: EntrySnapshot) -> None:
        """保存导航根和规范副本，不读写文件。"""
        self.root = root
        self.canonical = canonical
        self.steps: list[Step] = []
        self.directories: set[str] = set()
        self.sources: list[SourceAddition] = []
        self.roots: list[str] = []
        self.notices: list[PreviewNotice] = []
        self.counts: list[FieldChangeCount] = []

    def ensure_directory(self, path: PurePosixPath) -> None:
        """按父到子计划新目录，已有目录逐段用 O_NOFOLLOW 确认。"""
        for index in range(1, len(path.parts) + 1):
            relative = str(PurePosixPath(*path.parts[:index]))
            if relative in self.directories:
                continue
            candidate = self.root / relative
            if present(candidate):
                try:
                    with _io.directory(candidate):
                        pass
                except OSError as error:
                    raise nav_input_error(_RULE, "目的目录不是安全的普通目录") from error
            else:
                self.steps.append(MakeDirStep(path=relative))
                self.directories.add(relative)

    def write(self, path: str, before: bytes | None, after: bytes) -> None:
        """追加文件步骤，正文只保存在计划里。"""
        self.steps.append(
            WriteFileStep(
                path=path,
                before=image(before),
                after=image(after),
                after_content=after.decode("utf-8"),
            )
        )

    def link(
        self, location: EntryLocation, link: FirstLink, target: Target, manifest: JsonObject
    ) -> None:
        """只追加不存在的链接；已有副本同目标并已登记则保留。"""
        path = str(location.path / link.name)
        links = cast(list[JsonObject], manifest["links"])
        old = next((item for item in links if item.get("name") == link.name), None)
        if present(self.root / path):
            if (
                old
                and old.get("source_path") == target.path
                and (self.root / path).is_symlink()
                and str((self.root / path).readlink()) == target.path
            ):
                return
            raise nav_input_error(_RULE, "目的路径已存在，请改走改指向", objects=(("path", path),))
        if old is not None:
            raise nav_input_error(_RULE, "清单登记与实际链接不一致，请先处理")
        self.steps.append(SetLinkStep(path=path, before_target=None, after_target=target.path))
        links.append(
            {
                "name": link.name,
                "source_path": target.path,
                "source_type": target.kind,
                "entry_path": path,
            }
        )

    def extend_manifest(self, manifest: JsonObject, target: Target) -> None:
        """按 L3 追加不被覆盖的数据块和根，保持已有身份不变。"""
        sources = cast(list[JsonObject], manifest["sources"])
        if not any(under(target.path, str(item["direct_path"])) for item in sources):
            identifier = "src_" + hashlib.sha256(target.path.encode()).hexdigest()[:12]
            if any(item["source_id"] == identifier for item in sources):
                raise nav_input_error(_RULE, "新数据块 source_id 与已有编号冲突")
            added = SourceAddition(
                source_id=identifier,
                original_path=target.path,
                direct_path=target.path,
                format=target.format or "",
                version=target.version,
            )
            sources.append(
                cast(JsonObject, added.model_dump(mode="json")) | {"source_role": "data"}
            )
            self.sources.append(added)
        roots = cast(list[str], manifest["dataset_roots"])
        if not any(under(target.path, value) for value in roots):
            roots.append(target.path)
            self.roots.append(target.path)
            self.notices.append(
                PreviewNotice(
                    code="will_add_dataset_root",
                    message=f"将把 {target.path} 加进 dataset_roots",
                    objects=(("path", target.path),),
                )
            )
        for field, count in (
            ("links", 1),
            ("sources", len(self.sources)),
            ("dataset_roots", len(self.roots)),
        ):
            if count:
                self.counts.append(
                    FieldChangeCount(
                        file=str(self.canonical.location.path / REQUIRED_DOCUMENTS[0]),
                        field=field,
                        count=count,
                    )
                )

    def replicas(
        self,
        canonical: EntrySnapshot,
        existing: tuple[tuple[EntrySnapshot, dict[str, bytes]], ...],
        selected: tuple[EntryLocation, ...],
        link: FirstLink,
        target: Target,
    ) -> tuple[str, ...]:
        """全部副本重生成；只在勾选入口增加本条链接，来源文件不复制。"""
        known = {str(item.location.path): (item, raw) for item, raw in existing}
        locations = {key: value[0].location for key, value in known.items()} | {
            str(item.path): item for item in selected
        }
        selected_paths = {str(item.path) for item in selected}
        for path, location in sorted(locations.items()):
            if path in known:
                current, raw = known[path]
                manifest = payload(current, 0)
            else:
                if present(self.root / path):
                    raise nav_input_error(_RULE, "按格式入口目的已被其他对象占用")
                self.ensure_directory(location.path)
                current, raw = replace(canonical, location=location), {}
                manifest = payload(canonical, 0)
                manifest["links"] = []
            if path in selected_paths:
                self.link(location, link, target, manifest)
            files = tuple(
                dump_navigation_json(manifest)
                if index == 0
                else dump_navigation_json(payload(current, index))
                for index in range(3)
            )
            generated = generate_format_entry(canonical, with_documents(current, files))
            for file in generated.files:
                self.write(str(location.path / file.name), raw.get(file.name), file.content)
            if generated.omitted_source_ids:
                self.notices.append(
                    PreviewNotice(
                        code="source_not_reachable",
                        message=f"按格式入口不收录 {len(generated.omitted_source_ids)} 个链接不可达数据块",
                        objects=(
                            ("entry_path", path),
                            ("source_ids", ",".join(generated.omitted_source_ids)),
                        ),
                    )
                )
        return tuple(sorted(locations))

    def report(
        self,
        plan: NavWritePlan,
        target: Target,
        selected: tuple[EntryLocation, ...],
        formats: tuple[str, ...],
        *,
        noop: bool = False,
    ) -> PlanReport:
        """从同一份步骤投影有界展示字段，不重新作决定。"""
        files = tuple(item.path for item in plan.steps if isinstance(item, WriteFileStep))
        links = tuple(
            LinkAddition(path=item.path, target_path=item.after_target)
            for item in plan.steps
            if isinstance(item, SetLinkStep)
        )
        directories = tuple(item.path for item in plan.steps if isinstance(item, MakeDirStep))
        details = CreationDetails(
            canonical_entry_path=str(self.canonical.location.path),
            format_entry_paths=formats,
            selected_format_entry_paths=tuple(str(item.path) for item in selected)
            if not noop
            else (),
            file_paths=files,
            directory_paths=directories,
            links=links,
            sources_added=tuple(self.sources),
            dataset_roots_added=tuple(self.roots),
            resolved_format=target.format,
            resolved_version=target.version,
            metadata_source=target.metadata,
            noop=noop,
        )
        checks = (
            CheckNote(
                name="目标与元信息", scope=CheckScope.FULL, detail="仅检查本条目标；不递归质检数据"
            ),
            CheckNote(
                name="索引与大小",
                scope=CheckScope.AFTER_EXECUTION,
                detail="由公共写入作业更新索引并提交统计",
            ),
        )
        return PlanReport(
            file_count=len(files),
            link_count=len(links),
            directory_count=len(directories),
            field_counts=tuple(self.counts),
            listed_changes=(),
            listed_total=0,
            checks=checks,
            notices=tuple(self.notices),
            creation=details,
        )


def new_snapshot(
    location: EntryLocation, dataset_id: str, supplied: DatasetInformation | None = None
) -> EntrySnapshot:
    """构造新入口三份文档，按编号填入用户文字，未填项留空且不推测分类。"""
    from rdp.jobs.navwrite.create_models import INFORMATION_FIELD_NAMES

    manifest: JsonObject = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "dataset_name": location.dataset_name,
        "dataset_roots": [],
        "view": "task",
        "format": None,
        "version": None,
        "links": [],
        "sources": [],
    }
    values = {item.number: item.value_markdown for item in supplied.fields} if supplied else {}
    information: JsonObject = {
        "dataset_id": dataset_id,
        "title": f"{int(dataset_id.split('-')[-1])}. {location.dataset_name}",
        "fields": [
            {"number": index, "name": name, "value_markdown": values.get(index, "")}
            for index, name in enumerate(INFORMATION_FIELD_NAMES, 1)
        ],
    }
    if supplied is not None:
        classification: JsonObject = {
            "robot_model": supplied.robot_model,
            "scene": supplied.scene,
            "tasks": list(supplied.tasks),
        }
        for key, value in classification.items():
            if value:
                information[key] = value
    subtasks: JsonObject = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "dataset_name": location.dataset_name,
        "view": "task",
        "format": None,
        "version": None,
        "task_count": 0,
        "tasks": [],
    }
    documents = tuple(
        parse_document(location, name, dump_navigation_json(value))
        for name, value in zip(REQUIRED_DOCUMENTS, (manifest, information, subtasks), strict=True)
    )
    return EntrySnapshot(
        location=location,
        documents=documents,
        dataset_id=dataset_id,
        dataset_roots=(),
        links=(),
        sources=(),
        provenance_present=False,
        recorded_size_bytes=None,
        findings=(),
    )
