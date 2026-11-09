"""清洗类型装配（领域层，M4.5-02）；仅加载登记包，不访问工具程序或存储根。"""

from rdp.accounts.types import Role
from rdp.infra.config import ToolsConfig
from rdp.jobs.cleaning.job import CleaningDependencies, CleaningPreviewExecutor
from rdp.jobs.cleaning.parameters import cleaning_preview_type_name, tool_parameters
from rdp.jobs.registry import JobDefinition, JobRegistry
from rdp.jobs.types import RecoveryMode
from rdp.tools.manifest import read_package_manifest


def register_cleaning_jobs(
    registry: JobRegistry, tools: ToolsConfig, dependencies: CleaningDependencies | None
) -> None:
    """为每个具有清洗规则的有效工具登记管理员预览作业。

    Args:
        registry: 启动期间的类型登记表。
        tools: 登记包位置；仅使用 registry_dir。
        dependencies: worker 的只读执行能力，Web 必须传 None。

    Returns:
        无；没有 cleaning 规则的清单不生成预览类型。

    Raises:
        OSError: 登记目录或清单不可读取。
        DefectError: 归一化后的类型名称冲突或类型定义无效。

    Side Effects:
        读取登记包，更新内存登记表；不检查程序指纹、不访问存储根。

    Time Semantics:
        启动时登记一次；执行时重载当前清单，不支持自动恢复已中断的读取。
    """
    for package in sorted(tools.registry_dir.iterdir()):
        if not package.is_dir():
            continue
        manifest = read_package_manifest(package, tools.registry_dir)
        if manifest is None or not manifest.cleaning:
            continue
        registry.register(
            JobDefinition(
                cleaning_preview_type_name(manifest.tool.name),
                "清洗预览：" + manifest.tool.name,
                tool_parameters(manifest),
                RecoveryMode.INTERRUPT,
                CleaningPreviewExecutor(manifest.tool.name, dependencies).execute,
                submission_role=Role.ADMINISTRATOR,
            )
        )
