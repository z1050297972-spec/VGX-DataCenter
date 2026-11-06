"""作业类型显式登记（领域层，08）；对象由 Web/worker 各自构造并注入，不用可变单例。

Pydantic 负责参数校验；登记表只补稳定键、目录名和执行方式的业务约束。
参数会写入作业记录和日志开头，类型作者不得声明密码、令牌、cookie、私钥等字段，
也不得通过自由字典、命令行或配置文本绕过此限制；登记不能自动识别任意文本中的秘密。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, cast, get_args

from pydantic import AliasChoices, AliasPath, BaseModel, SecretBytes, SecretStr

from rdp.accounts.types import Role
from rdp.infra.actors import is_display_name
from rdp.infra.config import MAX_JOB_CONCURRENCY, StorageRootConfig
from rdp.infra.diagnostics import DefectError
from rdp.infra.ids import JOB_TYPE_KEY_PATTERN
from rdp.jobs._storage_requirements import validate_storage_uses
from rdp.jobs.policy import JOB_DISPLAY_NAME_MAX_CHARS
from rdp.jobs.types import RecoveryMode

if TYPE_CHECKING:
    from rdp.jobs.datasets.rescan import RescanDependencies
    from rdp.jobs.downloads.job import DownloadDependencies
    from rdp.jobs.execution import ExecutionContext
    from rdp.jobs.navwrite.pipeline import NavWriteDependencies


# 类型键是持久化协议；登记、执行装配、定时规则和HTTP入口共用，不复用历史含义。
EXAMPLE_GPU_TYPE = "example_gpu"
EXAMPLE_NAVIGATION_TYPE = "example_navigation"
PURGE_ERRORS_TYPE = "purge_errors"
PURGE_AUDIT_LOGS_TYPE = "purge_audit_logs"
# 清除作业固定名称也用于每日规则身份，不能作为可随意改写的界面文案。
PURGE_ERRORS_NAME = "清除过期报错"
PURGE_AUDIT_LOGS_NAME = "清除过期日志"
# 两个清除类型共用维护能力和重跑约束，避免登记校验与执行装配各维护一份集合。
MAINTENANCE_JOB_TYPES = frozenset({PURGE_ERRORS_TYPE, PURGE_AUDIT_LOGS_TYPE})


@dataclass(frozen=True)
class StorageUse:
    """类型作者声明的一项存储需求，不接受提交参数覆盖。

    Attributes:
        name: 配置里的存储根名字，匹配 JOB_TYPE_KEY_PATTERN。
        write: 严格 bool，默认 False；True 只请求新建权限，不允许修改已入库数据。
    """

    name: str
    write: bool = False


@dataclass(frozen=True)
class JobDefinition:
    """一个当前可执行类型，参数模型和执行函数成对登记。

    Attributes:
        type_name: 稳定英文键，匹配 [a-z][a-z0-9_]{0,63}，不可复用历史含义。
        display_name: 中文显示名兼目录分量，1-40 码点；无首尾空白、控制字符、斜杠、反斜杠，非 . 或 ..。
        parameters_model: BaseModel 子类，extra=forbid、hide_input_in_errors=True，无秘密字段。
        recovery_mode: resume/restart/interrupt 三选一，不由提交人覆盖。
        concurrency: 默认 1，严格整数 1 至 MAX_JOB_CONCURRENCY；配置可按类型覆盖。
        requires_gpu: 默认 False，严格布尔；True 时领取必须同时申请 GPU，空配置在执行时失败。
        storage: 按检查顺序排列的 StorageUse 元组，默认空，同一个根不可重复声明；
            名字须在启动配置中登记，用户不能用作业参数扩大该声明。
        writes_navigation: 默认 False，严格布尔（M1-07，ADR 0005 修订）。True 表示该类型会写导航层：
            "导航层恢复失败"标记存在时，worker 不领取这类作业，它们留在排队中；其他类型不受影响。
        submission_role: 提交所需最低角色；管理员可提交全部，成员仅可提交 MEMBER 类型，系统提交不受限。
        execute: 仅接收 ExecutionContext 的同步函数，成功返回 None；每一步至多 JOB_CHECKPOINT_MAX_S
            到达检查点，所有等待经上下文；异常由执行器外层收口，不自行写作业状态或结果。
    """

    type_name: str
    display_name: str
    parameters_model: type[BaseModel]
    recovery_mode: RecoveryMode
    execute: Callable[[ExecutionContext], None]
    concurrency: int = 1
    requires_gpu: bool = False
    storage: tuple[StorageUse, ...] = ()
    writes_navigation: bool = False
    submission_role: Role = Role.MEMBER


class JobRegistry:
    """一个入口私有的登记对象；启动前登记完成，工作期间只读，不跨线程变更。"""

    def __init__(self) -> None:
        """建立空登记表，允许测试登记隔离的类型。

        Args:
            无。

        Returns:
            无；每个实例互不共享登记内容。

        Raises:
            无。

        Side Effects:
            只分配实例内存，不自动导入插件或扫描目录。

        Time Semantics:
            同步构造，无时钟和等待；在线程启动前调用。
        """
        self._definitions: dict[str, JobDefinition] = {}

    def register(self, definition: JobDefinition) -> None:
        """登记类型并校验其身份和日志目录约束。

        Args:
            definition: 完整 JobDefinition；模型配置和执行函数满足上述类型作者约束。

        Returns:
            无；成功后按稳定英文键可查询，显示名也唯一。

        Raises:
            DefectError: 重复键/显示名、路径分量不合法、长度越界、非 Pydantic 模型、
                非 callable、恢复方式非法、concurrency 不是 1-MAX_JOB_CONCURRENCY 的严格整数、
                requires_gpu 不是 bool，或模型显式声明秘密字段/SecretStr/SecretBytes。
                storage 不是元组、成员不是 StorageUse、名字非法或重复、write 非 bool。

        Side Effects:
            原子增加一项；失败保持原表。不创建日志目录、不执行模型或作业。

        Time Semantics:
            启动期同步操作，不接受与 lookup 并发注册；无锁等待。
        """
        if not isinstance(cast(object, definition), JobDefinition) or not _valid_key(
            definition.type_name
        ):
            raise DefectError()
        validate_storage_uses(definition.storage)
        if (
            type(definition.concurrency) is not int
            or not 1 <= definition.concurrency <= MAX_JOB_CONCURRENCY
            or type(definition.requires_gpu) is not bool
            or not isinstance(cast(object, definition.submission_role), Role)
        ):
            raise DefectError()
        if definition.type_name in self._definitions:
            raise DefectError()
        if not isinstance(cast(object, definition.recovery_mode), RecoveryMode) or not callable(
            definition.execute
        ):
            raise DefectError()
        _check_model(definition.parameters_model, set())
        name = definition.display_name
        if (
            not is_display_name(name)
            or len(name) > JOB_DISPLAY_NAME_MAX_CHARS
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
            or any(item.display_name == name for item in self._definitions.values())
        ):
            raise DefectError()
        self._definitions[definition.type_name] = definition

    def validate_storage_roots(self, *, roots: tuple[StorageRootConfig, ...]) -> None:
        """完成登记时核对全部作业的根名，阻止带未知根的实例启动。

        Args:
            roots: 最终配置的不可变根元组，必填关键字；空配置必须显式传空元组。

        Returns:
            无；所有声明均能在 roots 中找到，空声明不要求有存储根。

        Raises:
            ValueError: 任一声明的名字未配置，含 type_name、storage_root、实际与期望及拒绝启动说明。
            DefectError: roots 不是已校验配置元组或登记内容违反 StorageUse 形状约束。

        Side Effects:
            无；只查内存，不检查在线、不更改登记、不拒绝声明写只读根的类型，后者在执行时失败。

        Time Semantics:
            Web/worker 在全部 register 完成后、接受提交或领取前调用一次；随后不再登记类型。
        """
        if type(roots) is not tuple or any(
            not isinstance(cast(object, root), StorageRootConfig) for root in roots
        ):
            raise DefectError()
        names = {root.name for root in roots}
        for definition in self.definitions():
            validate_storage_uses(definition.storage)
            for use in definition.storage:
                if use.name not in names:
                    raise ValueError(
                        f"type_name={definition.type_name} storage_root={use.name}：实际未登记；期望配置中存在该存储根；拒绝启动"
                    )

    def lookup(self, type_name: str) -> JobDefinition | None:
        """查找当前安装的类型，允许历史类型已经被移除。

        Args:
            type_name: 稳定英文类型键，1-64 字符。

        Returns:
            已登记定义，或 None 表示未登记；不猜相近名称。

        Raises:
            DefectError: 调用方传入非字符串或非法键形状。

        Side Effects:
            无；只读实例登记内容，未找到不新增占位类型。

        Time Semantics:
            常数时间字典查询，无时钟或 I/O。
        """
        if not _valid_key(type_name):
            raise DefectError()
        return self._definitions.get(type_name)

    def definitions(self) -> tuple[JobDefinition, ...]:
        """枚举可提交类型，供入口构造日志路径与页面选项。

        Args:
            无。

        Returns:
            按 type_name 升序的不可变元组，空表返回空元组。

        Raises:
            无。

        Side Effects:
            无；不暴露底层可变字典。

        Time Semantics:
            同步快照，不读取时间，不等待类型出现。
        """
        return tuple(self._definitions[key] for key in sorted(self._definitions))


def production_registry(
    rescan_dependencies: RescanDependencies | None = None,
    nav_write_dependencies: NavWriteDependencies | None = None,
    download_dependencies: DownloadDependencies | None = None,
) -> JobRegistry:
    """构造示例与维护作业的生产登记表。

    Args:
        rescan_dependencies: worker的显式扫描依赖；Web或只提交调用传None，不获得文件访问能力。
        nav_write_dependencies: worker的写导航层依赖（M1-07）；Web传None，只能校验提交参数，
            执行时缺依赖属于程序缺陷。
        download_dependencies: worker下载边界依赖；Web传None，仅校验参数。

    Returns:
        新 JobRegistry：示例、维护、数据集扫描与统计，以及 nav_write_apply、
        nav_revert_preview、两个创建预览、nav_data_origin_preview、nav_repoint_preview 和
        nav_fields_preview，以及 resume 的 download；扫描与预览为 restart，
        执行能力由入口显式注入。
        三个示例为 interrupt，两个清除为 restart；只有 example_gpu 需要 GPU，各类默认并发 1。

    Raises:
        DefectError: 示例类型的静态定义违反登记契约。

    Side Effects:
        只在返回对象登记，不创建目录、启动线程或缓存模块级实例。

    Time Semantics:
        Web 和 worker 启动时各调用一次并注入；无时钟、等待和自动发现。
    """
    # 延迟导入避免登记定义和执行上下文的模块环；每次构造都返回独立对象。
    from rdp.jobs.datasets.rescan import build_rescan_definition
    from rdp.jobs.datasets.sizing import build_sizing_definition
    from rdp.jobs.downloads.cleanup import (
        DeleteParameters,
        ProtectedDownloadExecutor,
        StagingDeleteExecutor,
    )
    from rdp.jobs.downloads.ingest import build_ingest_definitions
    from rdp.jobs.downloads.job import DownloadParameters
    from rdp.jobs.downloads.preview import PreviewExecutor
    from rdp.jobs.downloads.staging import ScanParameters, StagingScanner
    from rdp.jobs.example import CountParameters, execute_count
    from rdp.jobs.maintenance import PurgeParameters, execute_purge_errors, execute_purge_logs
    from rdp.jobs.navwrite.backfill import build_backfill_definition
    from rdp.jobs.navwrite.create_jobs import build_creation_definitions
    from rdp.jobs.navwrite.field_jobs import build_field_edit_definition
    from rdp.jobs.navwrite.jobs import build_navwrite_definitions
    from rdp.jobs.navwrite.repoint_jobs import build_repoint_definition
    from rdp.jobs.resource_examples import (
        GpuExampleParameters,
        NavigationExampleParameters,
        execute_gpu_example,
        execute_navigation_example,
    )

    registry = JobRegistry()
    registry.register(
        JobDefinition(
            "example_count",
            "示例：数数",
            CountParameters,
            RecoveryMode.INTERRUPT,
            execute_count,
            submission_role=Role.MEMBER,
        )
    )
    for definition in (
        JobDefinition(
            EXAMPLE_GPU_TYPE,
            "示例：占用 GPU",
            GpuExampleParameters,
            RecoveryMode.INTERRUPT,
            execute_gpu_example,
            submission_role=Role.ADMINISTRATOR,
            requires_gpu=True,
        ),
        JobDefinition(
            EXAMPLE_NAVIGATION_TYPE,
            "示例：写锁",
            NavigationExampleParameters,
            RecoveryMode.INTERRUPT,
            execute_navigation_example,
            submission_role=Role.ADMINISTRATOR,
        ),
        JobDefinition(
            PURGE_ERRORS_TYPE,
            PURGE_ERRORS_NAME,
            PurgeParameters,
            RecoveryMode.RESTART,
            execute_purge_errors,
            submission_role=Role.ADMINISTRATOR,
        ),
        JobDefinition(
            PURGE_AUDIT_LOGS_TYPE,
            PURGE_AUDIT_LOGS_NAME,
            PurgeParameters,
            RecoveryMode.RESTART,
            execute_purge_logs,
            submission_role=Role.ADMINISTRATOR,
        ),
    ):
        registry.register(definition)
    registry.register(
        JobDefinition(
            "download",
            "下载",
            DownloadParameters,
            RecoveryMode.RESUME,
            ProtectedDownloadExecutor(download_dependencies).execute,
            submission_role=Role.MEMBER,
        )
    )
    registry.register(
        JobDefinition(
            "download_preview",
            "下载预览",
            DownloadParameters,
            RecoveryMode.RESTART,
            PreviewExecutor(download_dependencies).execute,
            submission_role=Role.MEMBER,
        )
    )
    registry.register(
        JobDefinition(
            "download_staging_scan",
            "扫描下载暂存",
            ScanParameters,
            RecoveryMode.RESTART,
            StagingScanner(download_dependencies).execute,
            submission_role=Role.MEMBER,
        )
    )
    registry.register(
        JobDefinition(
            "download_staging_delete",
            "删除下载暂存",
            DeleteParameters,
            RecoveryMode.INTERRUPT,
            StagingDeleteExecutor(download_dependencies).execute,
            submission_role=Role.ADMINISTRATOR,
        )
    )
    registry.register(build_rescan_definition(rescan_dependencies))
    registry.register(build_sizing_definition(rescan_dependencies))
    for definition in (
        *build_navwrite_definitions(nav_write_dependencies),
        *build_creation_definitions(nav_write_dependencies),
        *build_ingest_definitions(nav_write_dependencies),
    ):
        registry.register(definition)
    registry.register(build_repoint_definition(nav_write_dependencies))
    registry.register(build_field_edit_definition(nav_write_dependencies))
    registry.register(build_backfill_definition(nav_write_dependencies))
    return registry


def _valid_key(value: object) -> bool:
    """按登记契约全匹配英文稳定键，不能接受末尾换行或隐式强制转换。"""
    return isinstance(value, str) and re.fullmatch(JOB_TYPE_KEY_PATTERN, value) is not None


# 显式秘密字段不能进入作业记录或日志；只识别字段/别名，不猜测任意业务文本是否含秘密。
_SECRET_PARAMETER_NAMES = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "access_token",
        "refresh_token",
        "api_key",
        "cookie",
        "private_key",
        "ssh_private_key",
        # 保留旧中文字段别名的拒绝规则；转义只避免与界面用词混淆，不能缩小秘密过滤范围。
        "\u53e3\u4ee4",
        "密码",
        "令牌",
        "私钥",
    }
)


def _check_model(value: object, seen: set[type[BaseModel]]) -> None:
    """遍历模型定义而不执行校验器；递归类型只访问一次，别名同样属于可被提交的字段。"""
    if not isinstance(value, type) or not issubclass(value, BaseModel):
        raise DefectError()
    if value in seen:
        return
    if (
        value.model_config.get("extra") != "forbid"
        or value.model_config.get("hide_input_in_errors") is not True
    ):
        raise DefectError()
    seen.add(value)
    for name, field in value.model_fields.items():
        names = [name, field.alias, field.serialization_alias, field.validation_alias]
        if any(_secret_alias(alias) for alias in names):
            raise DefectError()
        _check_annotation(field.annotation, seen)


def _secret_alias(value: object) -> bool:
    """字段的输入/输出别名也不能把秘密藏在一个看似安全的Python标识符后。"""
    if isinstance(value, str):
        return value.casefold() in _SECRET_PARAMETER_NAMES
    if isinstance(value, AliasChoices):
        return any(_secret_alias(choice) for choice in value.choices)
    if isinstance(value, AliasPath):
        return any(_secret_alias(part) for part in value.path)
    return False


def _check_annotation(value: object, seen: set[type[BaseModel]]) -> None:
    """容器、联合及嵌套模型中的秘密类型仍会落日志，不能仅检查顶层注解。"""
    if isinstance(value, type):
        if issubclass(value, (SecretStr, SecretBytes)):
            raise DefectError()
        if issubclass(value, BaseModel):
            _check_model(value, seen)
    for argument in get_args(value):
        _check_annotation(argument, seen)
