"""基础层 Alembic 执行环境（05），只复用 migrate 提供的连接，不配置进程日志。

骨架阶段不在导入时调度入口；实现阶段由 Alembic 加载本模块时调用 run_migrations。
手写 revision，无 script.py.mako：本票不提供 revision 自动生成命令，避免模板漏掉契约。
"""


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
    raise NotImplementedError
