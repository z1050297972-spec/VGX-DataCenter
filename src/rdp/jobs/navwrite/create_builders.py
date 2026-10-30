"""建链和新增数据集的预览构造（worker 领域层，M1-08、ADR 0009）。

只读导航与已登记本地存储根，返回第 07 张 PreviewBuild；不写导航、不实现 apply。
复用 reading、capture_preview_state、allocation、jsonio、replica、new_provenance；
目标检查使用已批准的 StorageAccessChecker 超时访问能力，不递归扫描真实数据。
"""

from collections.abc import Callable
from pathlib import PurePosixPath

from rdp.jobs.datasets.catalog import REQUIRED_DOCUMENTS
from rdp.jobs.datasets.reading import discover_entries
from rdp.jobs.datasets.rescan import RescanDependencies
from rdp.jobs.datasets.types import EntryLocation, View
from rdp.jobs.navwrite import _create_plan as plans
from rdp.jobs.navwrite import _create_read as reads
from rdp.jobs.navwrite.allocation import allocate_dataset_id
from rdp.jobs.navwrite.create_models import DatasetPreviewParameters, LinkPreviewParameters
from rdp.jobs.navwrite.errors import nav_input_error
from rdp.jobs.navwrite.jobs import PreviewBuild
from rdp.jobs.navwrite.jsonio import dump_navigation_json, regenerate_derived_fields
from rdp.jobs.navwrite.models import NavOperation, NavWritePlan
from rdp.jobs.navwrite.preview_state import capture_preview_state, verify_preview_state
from rdp.jobs.navwrite.provenance import ActorStamp, dump_provenance, new_provenance


def build_link_preview(
    dependencies: RescanDependencies,
    parameters: LinkPreviewParameters,
    *,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """为现有数据集构造建链计划与同源预览报告。

    Args:
        dependencies: worker 扫描依赖，导航根为绝对路径、存储检查器必需；
            仅支持登记的本地根，根可只读，NAS 在 12 的 1B 决定前拒绝。
        parameters: 已校验名称、目标及去重格式位置；dataset_id 必须对应唯一规范入口。
        checkpoint: 必填取消与停止检查点，每个入口、文件读块及存储调用之间触发。

    Returns:
        PreviewBuild，operation=create_link；步骤先 SetLinkStep 和规范副本原始路径.json 的
        WriteFileStep，再为全部已有及勾选的新按格式入口调用 generate_format_entry，
        新目录按父到子生成 MakeDirStep，每个入口三份 JSON 为 WriteFileStep。
        已有格式入口保留自己的 links[]，勾选入口追加本条链接及 SetLinkStep。
        links[] 追加并推导 entry_path；目标未被现有数据块覆盖才追加 sources[]，source_id
        首次分配后不重算，validation_status=path_exists_only；必要时追加 dataset_roots。
        有 meta/info.json 用其 format/version（LeRobot 元信息识别为 lerobot，
        codebase_version 去掉开头 v 得到版本，例如 v3.0 对应 3.0）；
        普通文件目标视为没有 meta/info.json；目录目标缺文件必须有 fallback_format，
        version=None；损坏或不可读的元信息不作为缺失降级。source_type 按目标为 file/directory，
        不接受特殊文件。新 source_id 为 src_ 加 original_path 的 sha256 前 12 位。
        L2 同目标且已登记时返回空步骤和 noop=True，不因格式勾选额外写入；
        该分支在元信息读取之前结束，metadata_source=not_checked、resolved_format/version=None，
        不要求无变化请求补填 fallback_format。
        report.creation 列完整差异，report.checks 区分全量路径检查与执行后索引/统计，
        report.notices 列根追加、L9 遗漏和 L10 推导字段变化；parameters 回显校验后的输入。

    Raises:
        InputError: 无唯一规范入口、JSON 不可用、格式位置重复或非法、目标非绝对/不存在/
            是软链接/在导航层内/原路径或 realpath 不属于登记根、目标为 NAS，或缺元信息
            未选格式、元信息损坏、不支持的格式版本；目的已存在且不满足 L2 时提示改走改指向。
            名称与四份 JSON 同名、格式入口冲突、源编号碰撞或读取超预算也拒绝。
        ExternalError: 存储根离线、挂载源不符、超时，或导航读取失败；不降级成目标不存在。
        ConflictError: 读取计划期间导航变化，读出的前像与 capture_preview_state 不一致。
        JobCancelledError: checkpoint 检出人为取消。
        WorkerStoppingError: checkpoint 检出 worker 停止。
        DefectError: 缺存储检查器、依赖或生成的计划违反约束。

    Side Effects:
        无（只读导航、挂载身份、目标与其 meta/info.json；不写目标、预览文件或数据库）。
        使用 capture_preview_state 覆盖规范入口和全部格式入口，包含来源.json；
        返回前再次确认读取前像一致，避免把过期正文与新的指纹组合成可执行预览。

    Time Semantics:
        不持写锁；存储调用沿用 StorageAccessChecker 的 access_timeout_s，
        取消检查间隔遵循作业框架预算。
        不读墙钟；执行时由 nav_write_apply 持锁复核同一份计划，不重新选择格式或重算规则。
    """
    state = capture_preview_state(
        dependencies.nav_root, (parameters.dataset_id,), None, checkpoint=checkpoint
    )
    paths = {item.path for dataset in state.datasets for item in dataset.entries}
    locations = [
        item for item in discover_entries(dependencies.nav_root).entries if str(item.path) in paths
    ]
    snapshots = [
        reads.snapshot(dependencies.nav_root, item, state, checkpoint) for item in locations
    ]
    canonical = [item for item in snapshots if item[0].location.view is View.TASK]
    if len(canonical) != 1:
        problem = nav_input_error("NAV_CREATE", "数据集必须有唯一按任务规范入口")
        raise problem
    current, raw = canonical[0]
    selected = plans.format_locations(current.location.dataset_name, parameters.format_entries)
    destination = dependencies.nav_root / current.location.path / parameters.link.name
    registered = any(
        item.name == parameters.link.name and item.source_path == parameters.link.target_path
        for item in current.links
    )
    noop = (
        reads.present(destination)
        and destination.is_symlink()
        and str(destination.readlink()) == parameters.link.target_path
        and registered
    )
    if reads.present(destination) and not noop:
        problem = nav_input_error("NAV_CREATE", "目的路径已存在，请改走改指向")
        raise problem
    target = reads.target(dependencies, parameters.link, checkpoint, metadata=not noop)
    planning = plans.Planning(dependencies.nav_root, current)
    formats: tuple[str, ...] = ()
    if not noop:
        manifest = plans.payload(current, 0)
        planning.link(current.location, parameters.link, target, manifest)
        planning.extend_manifest(manifest, target)
        content = dump_navigation_json(regenerate_derived_fields(manifest, current.location))
        planning.write(
            str(current.location.path / REQUIRED_DOCUMENTS[0]), raw[REQUIRED_DOCUMENTS[0]], content
        )
        updated = plans.with_documents(
            current, (content, raw[REQUIRED_DOCUMENTS[1]], raw[REQUIRED_DOCUMENTS[2]])
        )
        replicas = tuple(item for item in snapshots if item[0].location.view is View.FORMAT)
        formats = planning.replicas(updated, replicas, selected, parameters.link, target)
    verify_preview_state(dependencies.nav_root, state, checkpoint=checkpoint)
    plan = NavWritePlan(
        operation=NavOperation.CREATE_LINK,
        dataset_ids=(parameters.dataset_id,),
        steps=tuple(planning.steps),
        state=state,
    )
    return PreviewBuild(
        plan,
        planning.report(plan, target, selected, formats, noop=noop),
        parameters.model_dump(mode="json"),
    )


def build_dataset_preview(
    dependencies: RescanDependencies,
    parameters: DatasetPreviewParameters,
    set_by: ActorStamp,
    *,
    checkpoint: Callable[[], None],
) -> PreviewBuild:
    """构造新增数据集全套入口及第一条链接的预览计划。

    Args:
        dependencies: worker 扫描依赖，具有只读本地目标检查能力；不允许客户端覆盖导航根。
        parameters: 数据集名、必填来源、第一条链接及零到多个格式位置；不含 dataset_id。
        set_by: 从预览作业提交人生成的人工标注印记，包含账号编号、名字及注入的 UTC 时刻；
            显式选择未知也记录印记，不接受客户端操作者或时间。
        checkpoint: 取消/停止检查点，遍历导航入口及每个读块之间调用。

    Returns:
        PreviewBuild，operation=create_dataset，dataset_ids 只有预计新编号。
        复用 allocate_dataset_id，扫描按任务及已移除取最大值加一，至少两位；
        capture_preview_state 的 datasets 为空，new_dataset 记录目的不存在及最大编号。
        计划按父到子 MakeDirStep 创建规范入口，SetLinkStep 创建绝对目标链接，
        四个 WriteFileStep 写三份 JSON 及来源.json，再生成勾选格式入口的目录、链接和三份 JSON。
        数据集信息包含 dataset_id、title，title 为编号数字加 . 和数据集名，
        fields 复用 INFORMATION_FIELD_NAMES 的 14 项固定顺序，编号/名称齐全、value_markdown 空；
        子任务 tasks=[]、task_count=0；来源使用 new_provenance，collection_task_id=None、lineage=[]。
        按格式入口调用 generate_format_entry，不复制来源.json；链接与新数据块适用 L1/L3。
        report.creation 给出全套路径、来源数据块、根追加和预计编号对应入口；编号不是提前占用。

    Raises:
        InputError: 名称非法或按任务下同名对象存在（含断链）、第一链接不满足 L1/L3、
            格式选择重复/版本层不符、格式目的被占、来源不在 DATA_ORIGINS、编号扫描有坏入口，
            或元信息缺失未选格式、损坏及读取预算超限；无元信息时固定 version=None。
        ExternalError: 本地根离线/超时、挂载身份不符或导航读取失败。
        ConflictError: 构造期间目的或最大编号发生变化，不能组合不一致的预览。
        JobCancelledError: 用户取消预览，返回前的检查点终止构造。
        WorkerStoppingError: worker 停止，预览由 RESTART 从头构造。
        DefectError: 缺只读检查器、身份印记或生成结果违反模型约束。

    Side Effects:
        无（只读导航、已登记本地存储目标和 meta/info.json；不预建目录、不预占编号）。
        步骤的前像/后像交第 07 张日志与恢复流程，失败时构造不留下导航产物。

    Time Semantics:
        预览无锁，预计编号只对本次状态有效；执行在写锁下复核最大编号和目的不存在，
        变化则冲突，一行不写并要求重新预览，不把编号悄悄换成下一个。
        set_by.at 是预览记录时刻，不冒充实际写入时间；目标访问超时采用登记值。
    """
    location = EntryLocation(
        PurePosixPath("按任务", parameters.dataset_name),
        View.TASK,
        None,
        None,
        parameters.dataset_name,
    )
    destination = dependencies.nav_root / location.path
    if reads.present(destination):
        problem = nav_input_error("NAV_CREATE", "按任务下数据集名称已被占用")
        raise problem
    state = capture_preview_state(
        dependencies.nav_root, (), str(location.path), checkpoint=checkpoint
    )
    identifier = allocate_dataset_id(dependencies.nav_root)
    canonical = plans.new_snapshot(location, identifier)
    selected = plans.format_locations(parameters.dataset_name, parameters.format_entries)
    target = reads.target(dependencies, parameters.link, checkpoint)
    planning = plans.Planning(dependencies.nav_root, canonical)
    planning.ensure_directory(location.path)
    manifest = plans.payload(canonical, 0)
    planning.link(location, parameters.link, target, manifest)
    planning.extend_manifest(manifest, target)
    first = dump_navigation_json(regenerate_derived_fields(manifest, location))
    canonical = plans.with_documents(
        canonical,
        (
            first,
            dump_navigation_json(plans.payload(canonical, 1)),
            dump_navigation_json(plans.payload(canonical, 2)),
        ),
    )
    for document in canonical.documents:
        planning.write(
            str(location.path / document.name),
            None,
            dump_navigation_json(plans.payload(canonical, REQUIRED_DOCUMENTS.index(document.name))),
        )
    provenance = new_provenance(identifier, parameters.dataset_name, parameters.data_origin, set_by)
    planning.write(
        str(location.path / "来源.json"), None, dump_navigation_json(dump_provenance(provenance))
    )
    formats = planning.replicas(canonical, (), selected, parameters.link, target)
    verify_preview_state(dependencies.nav_root, state, checkpoint=checkpoint)
    plan = NavWritePlan(
        operation=NavOperation.CREATE_DATASET,
        dataset_ids=(identifier,),
        steps=tuple(planning.steps),
        state=state,
    )
    return PreviewBuild(
        plan, planning.report(plan, target, selected, formats), parameters.model_dump(mode="json")
    )
