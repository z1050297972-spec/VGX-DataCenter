"""转换输出身份的纯规则（M4.6-10）：只比较登记与作业记录，不解析链接或访问存储。

标准库 Path 足以做精确结构匹配；实际可达性、容量和防软链接访问由 worker 既有边界负责。
"""

from rdp.infra.config import StorageRootConfig
from rdp.infra.db.validation import invalid_field
from rdp.jobs.errors import JobInputError
from rdp.jobs.types import JobRecord


def select_root(roots: tuple[StorageRootConfig, ...], name: str | None) -> StorageRootConfig:
    """新提交省略名称时选首个可写根；显式选择不存在或只读时绝不回退。"""
    matches = (
        [root for root in roots if root.name == name]
        if name is not None
        else [root for root in roots if root.writable][:1]
    )
    if len(matches) != 1 or not matches[0].writable:
        raise JobInputError(
            invalid_field("output_root", "唯一已登记且可写的存储根名称").diagnostics
        )
    return matches[0]


def locate_root(
    roots: tuple[StorageRootConfig, ...],
    job_id: int,
    name: str | None,
    artifacts: tuple[str, ...],
    output_path: str | None,
) -> StorageRootConfig:
    """核对全部实际路径的精确归属；只有执行/提交边界可为无产物旧记录补默认根。"""
    selected = select_root(roots, name) if name is not None else None
    evidence = (*artifacts, *((output_path,) if output_path is not None else ()))
    if evidence:
        candidates: list[StorageRootConfig] = []
        for root in roots:
            stage = root.path / "暂存/转换" / str(job_id)
            allowed = {
                str(stage),
                str(stage / "out"),
                str(stage / "cleaned"),
                str(stage / "转换回执.json"),
            }
            # 比较原始文本而非 resolve，既拒绝 .. 和多余分隔，也不让 Web 触碰 NAS。
            if all(path in allowed for path in evidence) and (
                output_path is None or output_path in {str(stage / "out"), str(stage / "cleaned")}
            ):
                candidates.append(root)
        if len(candidates) != 1 or (selected is not None and selected != candidates[0]):
            raise JobInputError(
                invalid_field(
                    "output_root", "实际产物须唯一匹配该作业登记根下的暂存目录"
                ).diagnostics
            )
        return select_root(roots, candidates[0].name)
    if selected is not None:
        return selected
    raise JobInputError(
        invalid_field("output_root", "历史作业须记录实际产物或暂存目录，不能猜测存储根").diagnostics
    )


def record_root(
    roots: tuple[StorageRootConfig, ...], record: JobRecord, *, allow_default: bool = False
) -> StorageRootConfig:
    """从持久记录提取根身份；缺少实际路径的已执行旧作业不能按当前顺序迁移。"""
    name = record.parameters.get("output_root")
    if name is not None and not isinstance(name, str):
        raise JobInputError(invalid_field("output_root", "存储根名称文本").diagnostics)
    result = record.progress.conversion if record.progress is not None else None
    if allow_default and name is None and not record.artifacts and result is None:
        return select_root(roots, None)
    return locate_root(
        roots,
        record.job_id,
        name,
        record.artifacts,
        result.output_path if result is not None else None,
    )


def default_dataset_name(input_name: str) -> str:
    """预计路径与实际入库共用默认命名；占用和人工确认调整只在入库执行时处理。"""
    return input_name.removesuffix("_mcap") + "_lerobot"
