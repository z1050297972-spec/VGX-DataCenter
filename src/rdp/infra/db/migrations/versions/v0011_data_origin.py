"""0011 来源筛选编码扩展（基础层，M1-10）；保留既有索引、约束、外键与索引名。"""

from alembic import op

from rdp.infra.db.migrations.versions.v0001_error_reports import downgrade as _reject_downgrade

revision: str = "0011_data_origin"
down_revision: str = "0010_nav_write_foundation"
branch_labels: tuple[str, ...] | None = None
depends_on: str | None = None


def upgrade() -> None:
    """扩展数据集来源 CHECK，并保留所有已发布索引行。

    Args:
        无；Alembic 注入已有备份与写事务的连接。

    Returns:
        无；datasets.data_origin 新增五个已批准编码，unknown 继续有效。

    Raises:
        SQLAlchemyError: 建表、复制或恢复失败；由 migrate 回滚整个事务。

    Side Effects:
        同事务重建 datasets；先用临时表保存入口及三张子表，防止父表删除的 CASCADE 丢失索引。
        其余表和永久记录不变，不关闭外键校验，不读取导航层；失败保留迁移前备份。

    Time Semantics:
        仅停服务维护窗口运行；锁预算沿用 migrate，不读时钟或重试。
    """
    # SQLite 在已有事务里不能关闭 foreign_keys；先保存子表，再按父子顺序恢复，避免静默级联丢行。
    for statement in SAVE_CHILDREN_SQL:
        op.execute(statement)
    op.execute(CREATE_SQL)
    op.execute("INSERT INTO datasets_origin_0011 SELECT * FROM datasets")
    op.execute("DELETE FROM dataset_entries")
    op.execute("DROP TABLE datasets")
    op.execute("ALTER TABLE datasets_origin_0011 RENAME TO datasets")
    op.execute("CREATE INDEX ix_datasets_name ON datasets (name, dataset_id)")
    op.execute("CREATE INDEX ix_datasets_scan_id ON datasets (scan_id)")
    for statement in RESTORE_CHILDREN_SQL:
        op.execute(statement)


def downgrade() -> None:
    """拒绝会丢失已标注来源值的自动降级。

    Args:
        无；由 Alembic 调用。

    Returns:
        无；始终拒绝。

    Raises:
        InputError: 不支持自动降级，需恢复完整备份及匹配代码。

    Side Effects:
        无；保留当前结构和来源索引。

    Time Semantics:
        同步拒绝，不取时钟。
    """
    _reject_downgrade()


# 冻结子表顺序与 0011 DDL；只扩展来源 CHECK，不从会继续演进的 ORM 生成。
SAVE_CHILDREN_SQL = (
    "CREATE TEMP TABLE origin_0011_dataset_entries AS SELECT * FROM dataset_entries",
    "CREATE TEMP TABLE origin_0011_dataset_documents AS SELECT * FROM dataset_documents",
    "CREATE TEMP TABLE origin_0011_dataset_links AS SELECT * FROM dataset_links",
    "CREATE TEMP TABLE origin_0011_dataset_sources AS SELECT * FROM dataset_sources",
)
RESTORE_CHILDREN_SQL = (
    "INSERT INTO dataset_entries SELECT * FROM origin_0011_dataset_entries",
    "INSERT INTO dataset_documents SELECT * FROM origin_0011_dataset_documents",
    "INSERT INTO dataset_links SELECT * FROM origin_0011_dataset_links",
    "INSERT INTO dataset_sources SELECT * FROM origin_0011_dataset_sources",
    "DROP TABLE origin_0011_dataset_entries",
    "DROP TABLE origin_0011_dataset_documents",
    "DROP TABLE origin_0011_dataset_links",
    "DROP TABLE origin_0011_dataset_sources",
)
CREATE_SQL = "\nCREATE TABLE datasets_origin_0011 (\n\tdataset_id TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\tcanonical_entry_path TEXT, \n\tscan_id INTEGER NOT NULL, \n\tfingerprint JSON NOT NULL, \n\tdata_origin TEXT NOT NULL, \n\trecorded_size_bytes INTEGER, \n\tsize_bytes INTEGER, \n\tsize_checked_at TEXT, \n\tCONSTRAINT pk_datasets PRIMARY KEY (dataset_id), \n\tCONSTRAINT ck_datasets_identity CHECK (length(dataset_id) > 0 AND length(name) > 0), \n\tCONSTRAINT ck_datasets_origin CHECK (data_origin IN ('real','umi','ego','simulation','open_source','unknown')), \n\tCONSTRAINT ck_datasets_recorded_size CHECK (recorded_size_bytes IS NULL OR recorded_size_bytes >= 0), \n\tCONSTRAINT ck_datasets_size CHECK ((size_bytes IS NULL AND size_checked_at IS NULL) OR (size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL)), \n\tCONSTRAINT fk_datasets_scan_id_dataset_scans FOREIGN KEY(scan_id) REFERENCES dataset_scans (scan_id)\n)\n\n"
