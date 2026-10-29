"""0010 写导航层底座迁移（M1-07，ADR 0005 修订、ADR 0009 L14/L15），冻结 DDL，不依赖会随业务变化的 ORM。

本文件位于 pending；活动迁移图仍由 versions 目录唯一决定，获批后由 Claude 移入 versions 并让 ORM 与之对齐。
做两件事：
1. 新建单行表 nav_recovery_failure，保存全局标记"导航层恢复失败"（见 rdp.jobs.navwrite.marker）：

       CREATE TABLE nav_recovery_failure (
           singleton_id INTEGER NOT NULL,
           set_at TEXT NOT NULL,                 -- UTC 微秒，同 UTCDateTime 的存法
           job_ids JSON NOT NULL,                -- 留有对不上项的写入作业编号数组，升序、非空
           items JSON NOT NULL,                  -- MismatchItem 样例数组，至多 200 条
           total_items INTEGER NOT NULL,
           CONSTRAINT pk_nav_recovery_failure PRIMARY KEY (singleton_id),
           CONSTRAINT ck_nav_recovery_failure_singleton CHECK (singleton_id = 1),
           CONSTRAINT ck_nav_recovery_failure_total CHECK (total_items >= 1)
       )

   有这一行，写导航层的作业就被挡住；删除这一行（管理员确认）才放行。不新增作业状态。
2. 放宽 operation_logs.object_kind 的 CHECK，加入 'navigation_write'（沿用 0009 的"改名、重建、复制、删旧表、
   恢复 sqlite_sequence 高水位、重建两个索引"做法）。操作码是 operation 列里的文本，没有 CHECK，所以新增的七个
   操作码不需要改表。摘要字段（数据集、文件数、链接数、变更记录编号）在 details JSON 的白名单里，也不需要加列。
"""

revision: str = "0010_nav_write_foundation"
down_revision: str = "0009_rebuild_index_audit"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """创建恢复失败标记表，并放宽操作日志的对象种类约束。

    Args:
        无；使用 Alembic 当前连接及迁移入口已经持有的事务。

    Returns:
        无；nav_recovery_failure 为空表，operation_logs 全部历史行、索引和发号高水位保持不变。

    Raises:
        InputError: 原数据库损坏。
        ExternalError: DDL 或复制失败，由外层事务回滚并保留升级前备份。
        DefectError: 非 0009 结构或冻结 DDL 错误。

    Side Effects:
        新建一张表；重建 operation_logs 及其两个索引，保留 sqlite_sequence 高水位（已删除的高编号不复用，
        空表也保留）。不修改旧 revision，不读写导航层或状态目录。

    Time Semantics:
        Web/worker 全停后执行；锁与备份预算复用 migrate，无额外时钟或重试。
    """
    raise NotImplementedError


def downgrade() -> None:
    """拒绝降级：回到 0009 会丢失恢复失败标记，并让已写入的 navigation_write 日志违反约束。

    Args:
        无；由 Alembic 调用。

    Returns:
        无；始终拒绝。

    Raises:
        InputError: 不支持前向迁移的自动降级，沿用 versions 里 v0001 的统一拒绝。

    Side Effects:
        无；保留当前结构和全部数据。

    Time Semantics:
        即时拒绝，不重试。
    """
    raise NotImplementedError
