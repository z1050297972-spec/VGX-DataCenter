"""0007数据集索引迁移契约（基础层，M1-01），不改既有M0表和历史迁移。

版本脚本不依赖领域模型；活动DDL必须冻结在本版本，不能运行时从演进中的metadata生成。
"""

revision: str = "0007_dataset_index"
down_revision: str = "0006_platform_version"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """在迁移入口已有事务中创建八张可重建索引表及其约束和索引。

    Args:
        无；Alembic提供已备份、持迁移锁和写事务的连接。

    Returns:
        无；新增dataset_scans、dataset_scan_roots、datasets、dataset_entries、
        dataset_documents、dataset_links、dataset_sources、dataset_findings。
        列/类型/空值/CHECK/外键/索引与datasets.models声明逐项一致，UTC列用TEXT编码。
        数据集主键为永久dataset_id；入口主键为相对路径，可空dataset_id保留损坏入口；
        links/sources以入口和非负序号为主键，source_id不加全局唯一约束。

    Raises:
        SQLAlchemyError: 任一DDL或索引创建失败，由migrate统一映射既有四类异常。
        InputError: 源数据库版本/结构不满足0006前提，不猜测已有同名表可复用。

    Side Effects:
        八表及索引和版本号在同一事务生效，失败整体回滚且备份保留。
        不修改M0表、序列或记录，不导入领域模型、不调用create_all，不扫描导航或存储根。
        第02张磁盘/meta/大小列均建好，以NULL或unchecked表达尚未检查，不回填虚假值。

    Time Semantics:
        只在停Web/worker的维护窗口运行；锁预算沿用既有迁移入口，无自动重试或系统时钟。
    """
    raise NotImplementedError


def downgrade() -> None:
    """遵循平台只前进迁移策略拒绝自动降级。

    Args:
        无；不以索引可重建为理由删除其他版本的运行状态。

    Returns:
        无；任何调用均拒绝，提示停止服务后恢复完整备份及匹配代码。

    Raises:
        InputError: 任意降级请求，在执行DDL前拒绝。

    Side Effects:
        无；保留八张索引表、M0永久记录及当前版本号。

    Time Semantics:
        同步拒绝，不取时钟、不扫描导航、不等待其他服务退出。
    """
    raise NotImplementedError
