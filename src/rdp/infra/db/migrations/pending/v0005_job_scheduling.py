"""0005 作业资源与每日提交去重；冻结迁移不修改 0004，也不 import 可演进的领域模型。

本文件不在 Alembic 的 versions 搜索路径；新增模型独立于共用 MetaData，防止旧运行路径提前使用新列。
"""

revision = "0005_job_scheduling"
down_revision = "0004_jobs_worker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """原子扩展系统提交人、资源展示列及每日唯一提交表。

    Args:
        无；连接和事务由 Alembic 提供。

    Returns:
        无；成功版本为 0005_job_scheduling，既有作业和操作日志的值不变。

    Raises:
        ConflictError: 迁移写锁或约束竞争；不因有编号账号的历史名字为“系统”拒绝升级。
        InputError: 数据库损坏或源表记录不满足既有契约。
        ExternalError: 重建表、复制、索引或序列恢复 I/O 失败。
        DefectError: 版本前提、DDL 或列映射不一致。

    Side Effects:
        重建 jobs：submitter_id 可空，空编号必须 submitter_name='系统'；非空编号仍正整数，允许名字为“系统”的账号。
        新增 gpu_index NULL、wait_reason NULL、holds_navigation_lock NOT NULL DEFAULT 0，
        CHECK 约束与 scheduling_models 一致，原有全部列值、状态边、索引和日志路径唯一约束保留。
        重建 operation_logs，仅把空 actor_id 的固定名字约束放开为“运维”或“系统”，其他约束及索引不变。
        两张重建表先读取各自 sqlite_sequence，复制后恢复 max(旧序列,当前最大编号)，
        包括高编号行已删除及空表情形，保持 AUTOINCREMENT、不复用编号，不改旧迁移文本。
        新建 schedule_submissions，以 (schedule_name,local_date) 复合主键去重，job_id 唯一，
        索引 (schedule_name,job_id) 支持最近提交；日期是本地日历值，提交时刻用 UTC 文本。
        新建 worker_gpu_checks，保存每张配置卡的 instance_id、available、diagnostics 和 UTC checked_at；
        只作页面副本，实际可用集合由启动核对构造的内存池决定。
        整体由外层迁移事务提交；失败回滚，无新老结构混合或部分历史丢失。

    Time Semantics:
        不读取时钟、不提交定时作业；只在维护窗口且 worker 未运行时由受控迁移入口执行。
        锁/备份预算沿用第 5 张迁移入口，不自行无限重试。
    """
    raise NotImplementedError


def downgrade() -> None:
    """仅在没有会丢失的调度数据时恢复 0004 的结构。

    Args:
        无；使用 Alembic 当前连接及外层事务。

    Returns:
        无；安全降级后活动版本为 0004_jobs_worker。

    Raises:
        ConflictError: 存在系统提交作业、系统操作日志、任一定时提交行、非空 GPU/等待原因
            或真持锁标记、任意 worker_gpu_checks 行；拒绝丢失历史和资源信息，全部结构保持 0005。
        InputError: 存量数据库损坏。
        ExternalError: 重建/复制/删除表或序列恢复失败，整个事务回滚。
        DefectError: 非 0005 结构或冻结 DDL 不一致。

    Side Effects:
        先完成全部拒绝条件检查，再重建 jobs/operation_logs 为冻结 0004 定义并删除空定时表及空核卡表；
        保留旧行、索引与两表 AUTOINCREMENT 高水位，不改 0004 文件，不静默删系统历史。

    Time Semantics:
        不按时间猜数据可丢弃；维护窗口同步迁移，锁等待沿用入口预算。
    """
    raise NotImplementedError
