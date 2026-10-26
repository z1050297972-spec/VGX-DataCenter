"""0004 作业/心跳及审计 job 对象迁移；冻结 SQL 定义，不导入领域模型或运行时常量。

SQLite 不能直接修改 CHECK，operation_logs 在同一迁移事务中复制重建，必须保存 sqlite_sequence，
不能只按现存 MAX(log_id) 推算；保留期可能已经删掉最大编号的记录（08 负责人批准）。
"""

revision: str = "0004_jobs_worker"
down_revision: str = "0003_audit_login_logs"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """原子扩展审计对象 CHECK 并创建永久作业记录和单行心跳表。

    Args:
        无；Alembic 提供外层已备份、持有 BEGIN IMMEDIATE 的连接。

    Returns:
        无；新增 jobs/worker_heartbeat，列和约束与 0004 的抽象模型一致。
        jobs 主键 INTEGER PRIMARY KEY AUTOINCREMENT，无账号外键；UTC 时间 TEXT，
        JSON 参数/进度/诊断/摘要、独立计数和日志相对路径永久保存；
        (state,job_id)索引用于领取和状态筛选，全部列表按job_id复用主键索引，避免墙钟回拨打乱顺序。
        recovery_count为NOT NULL整数，默认0、CHECK范围0至3；新提交/重新提交从0开始，自动重跑不清零。
        log_path唯一，running/cancelling/completed/interrupted要求非空，与领取状态同事务写入。
        心跳 singleton_id=1，实例标识、pid、启动/最后心跳 UTC 时刻必填。

    Raises:
        SQLAlchemyError: 任一步 DDL、复制、序列恢复或索引创建失败，交 migrate 按既有四类映射。
        InputError: 原审计表/序列损坏或不能保证历史编号不复用，拒绝猜测并回滚。

    Side Effects:
        重建 operation_logs：所有旧列、记录、名字、编号、其他 CHECK 和两个原索引保持原样，
        只将 object_kind CHECK 从 account/audit_settings 扩为 account/audit_settings/job。
        删除旧表前读取其 sqlite_sequence.seq；复制后把新表序列恢复为
        max(重建前序列,重建后序列,现存最大编号)，空表和删除了历史最大编号也不降低高水位。
        不改 0003 脚本，不回填作业历史；表替换、序列、索引、新表和版本更新全在一个事务，
        任一步失败整体回滚至 0003，外层备份保留，不留下中间表或半套索引。

    Time Semantics:
        升级前停 Web/worker，由 migrate 持有迁移锁并备份；沿用单次 5 秒数据库锁预算，
        复制耗时取决于历史行数，按数据库执行，不在 Python 全量加载，无自动重试。
    """
    raise NotImplementedError


def downgrade() -> None:
    """按平台只前进迁移策略拒绝降级，保护永久作业和 job 审计记录。

    Args:
        无；即使当前没有 job 审计记录也不自动降级。

    Returns:
        无；始终拒绝，不删除任何表或记录。

    Raises:
        InputError: 任意调用，提示停服务后人工恢复完整备份及匹配版本代码。

    Side Effects:
        无；有 job 记录时不尝试转成 account、不丢弃记录，执行任何 DDL 前拒绝。

    Time Semantics:
        同步拒绝，无锁重试、时钟或数据扫描。
    """
    raise NotImplementedError
