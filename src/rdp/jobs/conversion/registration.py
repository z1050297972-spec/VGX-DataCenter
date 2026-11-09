"""转换类型装配（领域层，M4-03）；启动只读登记包，不访问工具库或数据盘。"""

from rdp.accounts.types import Role
from rdp.infra.config import StorageRootConfig, ToolsConfig
from rdp.jobs.conversion.cleanup import (
    CLEANUP_NAME,
    CLEANUP_TYPE,
    CleanupParameters,
    ConversionCleanup,
)
from rdp.jobs.conversion.job import ConversionDependencies, ConversionExecutor
from rdp.jobs.conversion.parameters import conversion_type_name, tool_parameters
from rdp.jobs.registry import JobDefinition, JobRegistry, StorageUse
from rdp.jobs.types import RecoveryMode
from rdp.tools.manifest import read_package_manifest


def register_conversion_jobs(
    registry: JobRegistry,
    tools: ToolsConfig,
    roots: tuple[StorageRootConfig, ...],
    dependencies: ConversionDependencies | None,
) -> None:
    """按登记包为Web与worker生成相同转换类型。

    Args:
        registry: 启动期尚未封闭的类型登记表。
        tools: 登记包位置，只读取registry_dir，不读取library_root。
        roots: 全部已登记存储根；首个可写根作为产物位置，输入根在执行时按选择声明。
        dependencies: worker执行能力；Web必须传None。

    Returns:
        无；有效清单各增加一个convert_类型。

    Raises:
        OSError: 登记包目录或文件不能读取。
        DefectError: 两个工具归一化后类型键冲突或生成定义不合法。

    Side Effects:
        只读登记包和配置路径，更新调用方内存登记；坏清单保留给工具列表展示但不生成类型。

    Time Semantics:
        启动时一次性登记；指纹检查留到作业第一阶段，工具执行前重新加载清单。
    """
    writable = next((root.name for root in roots if root.writable), None)
    if writable is not None:
        registry.register(
            JobDefinition(
                CLEANUP_TYPE,
                CLEANUP_NAME,
                CleanupParameters,
                RecoveryMode.RESTART,
                ConversionCleanup(dependencies).execute,
                storage=tuple(StorageUse(root.name, write=True) for root in roots if root.writable),
                submission_role=Role.ADMINISTRATOR,
            )
        )
    for package in sorted(tools.registry_dir.iterdir()):
        if not package.is_dir():
            continue
        manifest = read_package_manifest(package, tools.registry_dir)
        if manifest is None:
            continue
        registry.register(
            JobDefinition(
                conversion_type_name(manifest.tool.name),
                "转换：" + manifest.tool.name,
                tool_parameters(manifest),
                RecoveryMode.INTERRUPT,
                ConversionExecutor(manifest.tool.name, dependencies).execute,
                requires_gpu=manifest.runtime.needs_gpu,
                submission_role=Role.ADMINISTRATOR,
            )
        )
