"""0006 作业执行版本迁移（11 M2），冻结列定义，不依赖会随业务变化的 ORM。

本文件位于 pending；活动迁移图仍由 versions 目录唯一决定。
"""

revision = "0006_platform_version"
down_revision = "0005_job_scheduling"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """给作业表增加可空的平台执行版本列，保持历史事实不被伪造。

    Args:
        无；使用 Alembic 当前连接及迁移入口已经持有的事务。

    Returns:
        无；jobs 新增 platform_version VARCHAR(128)，允许 NULL，非空值长度 1-128。

    Raises:
        InputError: 原数据库损坏。
        ExternalError: 增列或 CHECK 创建失败，由外层事务回滚并保留升级前备份。
        DefectError: 非 0005 结构或冻结 DDL 错误。

    Side Effects:
        历史行全部保留 NULL，不拿升级时版本回填旧作业；只改 jobs 结构。
        保留原行、索引、约束和 sqlite_sequence 高水位，包括已删空但曾发号的表。

    Time Semantics:
        Web/worker 全停后执行；锁与备份预算复用 migrate，无额外时钟或重试。
    """
    raise NotImplementedError


def downgrade() -> None:
    """仅在没有执行版本事实会丢失时恢复 0005 作业结构。

    Args:
        无；复用 Alembic 当前连接和外层事务。

    Returns:
        无；移除 platform_version 并回到 0005，其他数据保持不变。

    Raises:
        ConflictError: 任意 platform_version 非 NULL；先拒绝，不丢执行历史。
        InputError: 存量数据库损坏。
        ExternalError: 表结构变更失败，全部回滚。
        DefectError: 非 0006 结构或 SQL 配置错误。

    Side Effects:
        先只读检查拒绝条件，再移除版本列及其 CHECK；保留其余约束、索引、记录和发号高水位。
        不修改旧 revision，不自动删除非空版本以凑降级条件。

    Time Semantics:
        停止两个服务后的维护窗口执行；不按记录年龄判断可否丢弃版本。
    """
    raise NotImplementedError
