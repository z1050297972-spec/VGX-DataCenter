"""作业类型显式登记（领域层，08）；对象由 Web/worker 各自构造并注入，不用可变单例。

Pydantic 负责参数校验；登记表只补稳定键、目录名和执行方式的业务约束。
参数会写入作业记录和日志开头，类型作者不得声明口令、令牌、cookie、私钥等字段，
也不得通过自由字典、命令行或配置文本绕过此限制；登记不能自动识别任意文本中的秘密。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel

from rdp.jobs.types import RecoveryMode

if TYPE_CHECKING:
    from rdp.jobs.execution import ExecutionContext


@dataclass(frozen=True)
class JobDefinition:
    """一个当前可执行类型，参数模型和执行函数成对登记。

    Attributes:
        type_name: 稳定英文键，匹配 [a-z][a-z0-9_]{0,63}，不可复用历史含义。
        display_name: 中文显示名兼目录分量，1-40 码点；无首尾空白、控制字符、斜杠、反斜杠，非 . 或 ..。
        parameters_model: BaseModel 子类，extra=forbid、hide_input_in_errors=True，无秘密字段。
        recovery_mode: resume/restart/interrupt 三选一，不由提交人覆盖。
        execute: 仅接收 ExecutionContext 的同步函数，成功返回 None；每一步至多 JOB_CHECKPOINT_MAX_S
            到达检查点，所有等待经上下文；异常由执行器外层收口，不自行写作业状态或结果。
    """

    type_name: str
    display_name: str
    parameters_model: type[BaseModel]
    recovery_mode: RecoveryMode
    execute: Callable[[ExecutionContext], None]


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
        raise NotImplementedError

    def register(self, definition: JobDefinition) -> None:
        """登记类型并校验其身份和日志目录约束。

        Args:
            definition: 完整 JobDefinition；模型配置和执行函数满足上述类型作者约束。

        Returns:
            无；成功后按稳定英文键可查询，显示名也唯一。

        Raises:
            DefectError: 重复键/显示名、路径分量不合法、长度越界、非 Pydantic 模型、
                非 callable、恢复方式非法，或模型显式声明秘密字段/SecretStr/SecretBytes。

        Side Effects:
            原子增加一项；失败保持原表。不创建日志目录、不执行模型或作业。

        Time Semantics:
            启动期同步操作，不接受与 lookup 并发注册；无锁等待。
        """
        raise NotImplementedError

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
        raise NotImplementedError

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
        raise NotImplementedError


def production_registry() -> JobRegistry:
    """构造仅含“示例：数数”的生产登记表。

    Args:
        无。

    Returns:
        新 JobRegistry，类型键 example_count；恢复方式为标记中断。

    Raises:
        DefectError: 示例类型的静态定义违反登记契约。

    Side Effects:
        只在返回对象登记，不创建目录、启动线程或缓存模块级实例。

    Time Semantics:
        Web 和 worker 启动时各调用一次并注入；无时钟、等待和自动发现。
    """
    raise NotImplementedError
