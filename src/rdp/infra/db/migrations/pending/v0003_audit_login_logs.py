"""基础层 0003 迁移契约（07），暂存 pending，不被运行中的迁移图发现。

迁移移入 versions 必须与 audit.models 注册表同步；冻结列/约束/索引的 SQL，
不能从领域导入模型或常量，防止旧迁移随业务代码变化（规范 1.1）。
"""

revision: str = "0003_audit_login_logs"
down_revision: str = "0002_accounts_sessions"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """在已有迁移事务里创建两种日志表和共同保留期设置表。

    Args:
        无；由 Alembic 提供已备份且持有 BEGIN IMMEDIATE 的连接。

    Returns:
        无；operation_logs/login_logs/audit_settings 的列、CHECK 和索引与 07 模型一致；
        日志主键 AUTOINCREMENT，无账号外键；UTC 时间底层 TEXT，明细为 JSON。
        每种日志建 (occurred_at,log_id) 和 (账号编号,occurred_at,log_id) 索引；不建默认设置行。

    Raises:
        SQLAlchemyError: 任一 DDL、约束、锁或 I/O 失败；由外层 migrate 归入既有四类异常。

    Side Effects:
        仅新建三张表及索引，不更改既有账号/会话/报错数据，不回填历史日志；失败整个事务回滚，
        head 保持 0002，外层保留升级前备份。默认保留期 30，数据库约束 7-365，不安装调度任务。

    Time Semantics:
        备份和获锁已由 migrate 完成；沿用外层单次 5000 毫秒锁预算，无额外重试或时钟读取。
    """
    raise NotImplementedError


def downgrade() -> None:
    """拒绝自动降级，避免静默丢失历史日志。

    Args:
        无。

    Returns:
        无；始终拒绝降级。

    Raises:
        InputError: 所有调用；提示停服务后人工恢复备份及匹配代码。

    Side Effects:
        无；执行任何删除 SQL 之前拒绝。

    Time Semantics:
        同步拒绝，无等待、时钟或重试。
    """
    raise NotImplementedError
