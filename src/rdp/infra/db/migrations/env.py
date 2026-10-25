"""基础层 Alembic 执行环境（05），只复用 migrate 提供的连接，不配置进程日志。

Alembic 加载时已有 context.config 才调度入口；普通 import 不触发迁移。
手写 revision，无 script.py.mako：本票不提供 revision 自动生成命令，避免模板漏掉契约。
"""

from alembic import context
from sqlalchemy import Connection

from rdp.infra.db.models import metadata
from rdp.infra.diagnostics import DefectError


def run_migrations() -> None:
    """在调用者的单个事务中执行 Alembic 在线迁移。

    Args:
        无；使用 Alembic context.config.attributes 中 migrate 注入的 connection。

    Returns:
        无；target_metadata 使用 models.metadata，render_as_batch=True、compare_type=True、
        transactional_ddl=True，不另开引擎或提交调用者事务。

    Raises:
        DefectError: 缺少在线连接或使用离线模式；不猜 URL、不读 alembic.ini。
        Exception: Alembic 配置/脚本/SQL 执行失败，向 migrate 传播，由它统一归四类异常。

    Side Effects:
        在现有事务中执行迁移；失败由 migrate 回滚，保留升级前备份。
        不调用 logging.config.fileConfig，不更改任何全局 logger，不写日志。

    Time Semantics:
        migrate 已取得迁移锁和数据库写事务后才运行；不读时钟、不重试。
    """
    config = getattr(context, "config", None)
    connection = config.attributes.get("connection") if config is not None else None
    if not isinstance(connection, Connection) or context.is_offline_mode():
        raise DefectError()
    context.configure(
        connection=connection,
        target_metadata=metadata,
        render_as_batch=True,
        compare_type=True,
        transactional_ddl=True,
    )
    with context.begin_transaction():
        context.run_migrations()


# Alembic EnvironmentContext 在加载脚本前安装 config 代理；普通 Python 导入没有此代理。
if hasattr(context, "config"):
    run_migrations()
