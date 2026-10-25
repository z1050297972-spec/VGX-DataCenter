"""基础层第二版迁移契约（06），冻结 SQL，不反向引用账号领域模型。

骨架暂放 pending，现有迁移 head 仍为 0001；实现时移到 versions 并激活账号模型。
复用 migrate 的备份、BEGIN IMMEDIATE、事务回滚与前向迁移规则，不另建迁移器。
"""

revision: str = "0002_accounts_sessions"
down_revision: str = "0001_error_reports"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """创建账号、会话表及索引。

    Args:
        无；由 Alembic 提供持有写事务的在线连接。

    Returns:
        无；accounts、account_sessions 的列和命名约束与 06 模型逐项相同；
        时间底层 TEXT；accounts 使用 SQLite AUTOINCREMENT，会话外键 ON DELETE CASCADE；
        不创建默认账号，不改 error_reports 或已有报错数据。

    Raises:
        SQLAlchemyError: DDL、锁、约束或 I/O 失败；由外层 migrate 转成四类异常。

    Side Effects:
        只在当前事务创建两表和会话 account_id/last_seen_at 索引；失败整体回滚，
        版本停留 0001，不留半张表；外层保留完整升级前备份，不自动恢复。

    Time Semantics:
        必须在 migrate 完成备份并取得 BEGIN IMMEDIATE 后执行，无时钟读取、自动重试或降级。
    """
    raise NotImplementedError


def downgrade() -> None:
    """拒绝第二版降级，避免破坏账号和会话。

    Args:
        无。

    Returns:
        无；不正常返回。

    Raises:
        InputError: 所有调用均拒绝，提示停止服务后人工恢复备份和匹配代码。

    Side Effects:
        无；执行 SQL 之前拒绝，不删除任何数据或自动恢复。

    Time Semantics:
        同步立即拒绝，无时钟、等待或重试。
    """
    raise NotImplementedError
