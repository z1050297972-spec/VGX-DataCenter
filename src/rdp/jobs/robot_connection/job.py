"""连接检查作业定义；共用会话负责身份、SSH、网络和就绪，不自动启动预览。"""

from rdp.infra.diagnostics import DefectError
from rdp.jobs.execution import ExecutionContext
from rdp.jobs.registry import JobDefinition
from rdp.jobs.robot_connection._session import (
    ConnectionDependencies as ConnectionDependencies,
)
from rdp.jobs.robot_connection._session import (
    ConnectionParameters as ConnectionParameters,
)
from rdp.jobs.robot_connection._session import (
    connect,
)
from rdp.jobs.types import RecoveryMode

CONNECTION_JOB_TYPE = "robot_connection_check"


def build_connection_definition(dependencies: ConnectionDependencies | None) -> JobDefinition:
    """登记无需 GPU 或存储根的机器人连接检查类型。

    Args:
        dependencies: worker 的数据库、状态目录、说明档快照和可信程序路径；Web 传 None，仅能提交。

    Returns:
        默认并发 1、恢复方式 interrupt 的检查机器人连接定义。

    Raises:
        无。

    Side Effects:
        仅构造定义，不生成密钥、不启动进程、不访问网络。

    Time Semantics:
        启动期同步登记；中断后需人工重提，避免恢复时意外连接机器人。
    """

    def execute(context: ExecutionContext) -> None:
        if dependencies is None or not isinstance(context.parameters, ConnectionParameters):
            raise DefectError()
        connect(context, dependencies)

    return JobDefinition(
        CONNECTION_JOB_TYPE, "检查机器人连接", ConnectionParameters, RecoveryMode.INTERRUPT, execute
    )
