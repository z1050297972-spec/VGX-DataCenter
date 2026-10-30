"""改指向的只读 worker 预览构造（M1-09、L8/L17-L19）。

复用导航安全读取、JSON 编码、格式副本生成与状态指纹；只产出底座计划，不自行写入。
前缀替换是本票的业务规则，标准库 re 负责匹配；不读取来源文件正文或改 source_id。
"""

from collections.abc import Callable
from typing import cast

from rdp.jobs.datasets.catalog import REQUIRED_DOCUMENTS
from rdp.jobs.datasets.reading import discover_entries
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.datasets.types import EntrySnapshot, JsonObject, View
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite import _create_read as reads
from rdp.jobs.navwrite._repoint_targets import check_targets
from rdp.jobs.navwrite._repoint_text import Replacements
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.jsonio import (
    dump_navigation_json,
    load_navigation_json,
    regenerate_derived_fields,
)
from rdp.jobs.navwrite.models import (
    CheckNote,
    CheckScope,
    FieldChangeCount,
    NavOperation,
    NavWritePlan,
    PlanReport,
    PreviewNotice,
    SetLinkStep,
)
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.navwrite.replica import generate_format_entry
from rdp.jobs.navwrite.repoint_models import RepointParameters


def build_repoint_preview(
    dependencies: RescanDependencies,
    parameters: RepointParameters,
    *,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """构造单个数据集两个视图的前缀替换计划。

    Args:
        dependencies: worker 的受管扫描依赖，导航根为绝对路径；目标只允许登记本地根。
        parameters: 数据集编号及不带结尾斜杠的绝对新旧前缀。
        checkpoint: 必填取消/停止检查点，每个入口及字符串遍历间调用。

    Returns:
        operation=repoint_dataset 的 PreviewBuild；先写规范副本，再由其重新生成全部格式入口。
        三份 JSON 的字符串值适用 L17，original_path 及来源文件保持原样；
        report 给出分字段计数、Markdown/notes 逐处差异和 L9 遗漏。

    Raises:
        InputError: 无唯一规范入口、三份 JSON 无法读取、目标越界或为 NAS，
            或旧路径存在但任一新路径缺失、完整正文差异超预算；整批拒绝。
        ExternalError: 导航读取失败或存储根离线、身份不符、访问超时。
        ConflictError: 构造期间导航状态变化。
        JobCancelledError: 检查点收到取消。
        WorkerStoppingError: 检查点收到停止。
        DefectError: worker 依赖缺失或生成计划违反既有模型。

    Side Effects:
        无（只读导航层和登记存储根；不写导航、预览文件、数据库或数据目标）。

    Time Semantics:
        不持写锁、不读墙钟；存储检查使用登记的访问超时。
        指纹反映预览时刻，nav_write_apply 在写锁内核对同一计划，变化则一行不写。
    """
    return _Planning(dependencies, parameters, checkpoint).build()


class _Planning:
    """一次 worker 预览的只读上下文，按规范入口到格式入口装配计划。"""

    def __init__(
        self, deps: RescanDependencies, params: RepointParameters, checkpoint: Callable[[], None]
    ) -> None:
        """先捕获指纹，再把所有读取前像与它对齐。"""
        self.deps, self.params, self.checkpoint = deps, params, checkpoint
        self.state = capture_preview_state(
            deps.nav_root, (params.dataset_id,), None, checkpoint=checkpoint
        )
        paths = {item.path for dataset in self.state.datasets for item in dataset.entries}
        self.snapshots = [
            reads.snapshot(deps.nav_root, location, self.state, checkpoint)
            for location in discover_entries(deps.nav_root).entries
            if str(location.path) in paths
        ]
        canonical = [item for item in self.snapshots if item[0].location.view is View.TASK]
        if len(canonical) != 1:
            problem = nav_input_error("NAV_REPOINT", "数据集必须有唯一按任务规范入口")
            raise problem
        self.current, _raw = canonical[0]
        self.planning = plans.Planning(deps.nav_root, self.current)
        self.text = Replacements(params.old_prefix, params.new_prefix, checkpoint)
        self.omissions: list[PreviewNotice] = []

    def build(self) -> PreviewBuild:
        """先替换规范正文，再生成全部格式入口；完成存储校验后复核指纹。"""
        updated = [(self._updated(original), raw) for original, raw in self.snapshots]
        canonical = next(item for item, _ in updated if item.location.view is View.TASK)
        # L8 规定规范副本必须先写，格式入口才可按它重建。
        for entry, raw in sorted(updated, key=lambda item: item[0].location.view is View.FORMAT):
            generated = self._files(canonical, entry)
            for name, content in generated:
                self.planning.write(str(entry.location.path / name), raw[name], content)
            self._links(entry)
        notices = (*check_targets(self.deps, self.text.paths, self.checkpoint), *self.omissions)
        verify_preview_state(self.deps.nav_root, self.state, checkpoint=self.checkpoint)
        plan = NavWritePlan(
            operation=NavOperation.REPOINT_DATASET,
            dataset_ids=(self.params.dataset_id,),
            steps=tuple(self.planning.steps),
            state=self.state,
        )
        return PreviewBuild(plan, self._report(plan, notices), self.params.model_dump(mode="json"))

    def _updated(self, original: EntrySnapshot) -> EntrySnapshot:
        """格式入口只取替换后的 links，报告随后按规范副本计算，避免统计被丢弃正文。"""
        files = tuple(
            dump_navigation_json(
                cast(
                    JsonObject,
                    self.text.transform(
                        plans.payload(original, index),
                        str(original.location.path / name),
                        record=original.location.view is View.TASK,
                    ),
                )
            )
            for index, name in enumerate(REQUIRED_DOCUMENTS)
        )
        return plans.with_documents(original, files)

    def _files(
        self, canonical: EntrySnapshot, entry: EntrySnapshot
    ) -> tuple[tuple[str, bytes], ...]:
        """使用 L8 唯一生成器，规范副本按 L10 重新推导字段。"""
        if entry.location.view is View.TASK:
            return tuple(
                (
                    name,
                    dump_navigation_json(
                        plans.payload(entry, index)
                        if index == 1
                        else regenerate_derived_fields(plans.payload(entry, index), entry.location)
                    ),
                )
                for index, name in enumerate(REQUIRED_DOCUMENTS)
            )
        original = next(item for item, _ in self.snapshots if item.location == entry.location)
        # 报告取 L8 生成前的规范正文，而非即将丢弃的旧格式正文。
        baseline = generate_format_entry(self.current, original)
        for file in baseline.files:
            self.text.transform(
                load_navigation_json(file.content), str(entry.location.path / file.name)
            )
        replica = generate_format_entry(canonical, entry)
        self.omissions.extend(
            PreviewNotice(
                code="source_not_reachable",
                message="按格式入口不收录链接够不着的数据块",
                objects=(("entry_path", str(entry.location.path)), ("source_id", source_id)),
            )
            for source_id in replica.omitted_source_ids
        )
        return tuple((item.name, item.content) for item in replica.files)

    def _links(self, entry: EntrySnapshot) -> None:
        """实际 readlink 前像也参加 L19，避免未登记的实际链接逃过检查。"""
        fingerprint = next(
            item
            for dataset in self.state.datasets
            for item in dataset.entries
            if item.path == str(entry.location.path)
        )
        for link in fingerprint.links:
            if link.target is None:
                raise nav_input_error(
                    "NAV_REPOINT", "链接前像无法读取", objects=(("link", link.name),)
                )
            after = self.text.path_pattern.sub(lambda _match: self.params.new_prefix, link.target)
            if after != link.target:
                self.text.paths[link.target] = after
                self.planning.steps.append(
                    SetLinkStep(
                        path=str(entry.location.path / link.name),
                        before_target=link.target,
                        after_target=after,
                    )
                )

    def _report(self, plan: NavWritePlan, notices: tuple[PreviewNotice, ...]) -> PlanReport:
        """报告计数来自同一计划，路径替换检查与执行后检查明确区分。"""
        return PlanReport(
            file_count=sum(step.op == "write_file" for step in plan.steps),
            link_count=sum(step.op == "set_link" for step in plan.steps),
            directory_count=0,
            field_counts=tuple(
                FieldChangeCount(file=file, field=field, count=count)
                for (file, field), count in self.text.counts.items()
            ),
            listed_changes=tuple(self.text.listed),
            listed_total=self.text.listed_total,
            repoint_changes=tuple(self.text.complete),
            checks=(
                CheckNote(
                    name="导航状态及替换路径",
                    scope=CheckScope.FULL,
                    detail="全部入口 L12 指纹；旧位置存在的每个引用及实际链接的新位置均已核对",
                ),
                CheckNote(
                    name="索引与大小",
                    scope=CheckScope.AFTER_EXECUTION,
                    detail="写入后更新索引并提交统计大小作业，预览不递归扫描数据",
                ),
            ),
            notices=notices,
        )
