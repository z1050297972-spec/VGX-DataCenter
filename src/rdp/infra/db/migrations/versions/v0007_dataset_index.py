"""0007数据集索引迁移契约（基础层，M1-01），不改既有M0表和历史迁移。

版本脚本不依赖领域模型；活动DDL必须冻结在本版本，不能运行时从演进中的metadata生成。
"""

from alembic import op
from sqlalchemy import text

from rdp.infra.db.validation import invalid_field

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
    for statement in _TABLE_DDL:
        op.execute(text(statement))
    for statement in _INDEX_DDL:
        op.execute(text(statement))


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
    problem = invalid_field("revision", "停止服务后恢复完整备份及匹配版本代码")
    raise problem


# 0007冻结DDL；生成时核对声明，运行时不导入演进中的领域模型。
_TABLE_DDL = (
    "\nCREATE TABLE dataset_scans (\n\tscan_id INTEGER NOT NULL, \n\tjob_id INTEGER, \n\tscope TEXT NOT NULL, \n\trequested_dataset_id TEXT, \n\tstarted_at TEXT NOT NULL, \n\tnavigation_finished_at TEXT NOT NULL, \n\tcommitted_at TEXT NOT NULL, \n\tnavigation_elapsed_s FLOAT NOT NULL, \n\tlock_held_s FLOAT NOT NULL, \n\tstorage_stage TEXT NOT NULL, \n\tis_current BOOLEAN NOT NULL, \n\tCONSTRAINT pk_dataset_scans PRIMARY KEY (scan_id), \n\tCONSTRAINT ck_dataset_scans_ids CHECK (scan_id > 0 AND (job_id IS NULL OR job_id > 0)), \n\tCONSTRAINT ck_dataset_scans_scope CHECK ((scope = 'all' AND requested_dataset_id IS NULL) OR (scope = 'dataset' AND requested_dataset_id IS NOT NULL AND length(requested_dataset_id) > 0)), \n\tCONSTRAINT ck_dataset_scans_duration CHECK (navigation_elapsed_s >= 0 AND lock_held_s >= 0), \n\tCONSTRAINT ck_dataset_scans_storage_stage CHECK (storage_stage IN ('not_run','completed')), \n\tCONSTRAINT ck_dataset_scans_current_boolean CHECK (is_current IN (0,1))\n)\n\n",
    "\nCREATE TABLE dataset_findings (\n\towner_key TEXT NOT NULL, \n\t\"group\" TEXT NOT NULL, \n\tseverity TEXT NOT NULL, \n\trule TEXT NOT NULL, \n\tscan_id INTEGER NOT NULL, \n\ttotal INTEGER NOT NULL, \n\tsamples JSON NOT NULL, \n\tCONSTRAINT pk_dataset_findings PRIMARY KEY (owner_key, \"group\", severity, rule), \n\tCONSTRAINT ck_dataset_findings_identity_count CHECK (length(owner_key) > 0 AND length(rule) > 0 AND total > 0), \n\tCONSTRAINT ck_dataset_findings_group CHECK (\"group\" IN ('json','views','disk','storage')), \n\tCONSTRAINT ck_dataset_findings_severity CHECK (severity IN ('action_required','notice')), \n\tCONSTRAINT fk_dataset_findings_scan_id_dataset_scans FOREIGN KEY(scan_id) REFERENCES dataset_scans (scan_id)\n)\n\n",
    "\nCREATE TABLE dataset_scan_roots (\n\tscan_id INTEGER NOT NULL, \n\tname TEXT NOT NULL, \n\tpath TEXT NOT NULL, \n\tuuid TEXT, \n\tnfs_export TEXT, \n\twritable BOOLEAN NOT NULL, \n\tonline BOOLEAN, \n\treason TEXT, \n\tchecked_at TEXT, \n\tCONSTRAINT pk_dataset_scan_roots PRIMARY KEY (scan_id, name), \n\tCONSTRAINT ck_dataset_scan_roots_identity CHECK (length(name) > 0 AND length(path) > 0), \n\tCONSTRAINT ck_dataset_scan_roots_writable CHECK (writable IN (0,1)), \n\tCONSTRAINT ck_dataset_scan_roots_source CHECK ((uuid IS NOT NULL AND length(uuid) > 0 AND nfs_export IS NULL) OR (uuid IS NULL AND nfs_export IS NOT NULL AND length(nfs_export) > 0)), \n\tCONSTRAINT ck_dataset_scan_roots_status CHECK ((online IS NULL AND reason IS NULL AND checked_at IS NULL) OR (online IS NOT NULL AND ((online = 1 AND reason IS NULL AND checked_at IS NOT NULL) OR (online = 0 AND reason IS NOT NULL AND reason IN ('not_mounted','source_mismatch','timeout') AND checked_at IS NOT NULL)))), \n\tCONSTRAINT fk_dataset_scan_roots_scan_id_dataset_scans FOREIGN KEY(scan_id) REFERENCES dataset_scans (scan_id) ON DELETE CASCADE\n)\n\n",
    "\nCREATE TABLE datasets (\n\tdataset_id TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\tcanonical_entry_path TEXT, \n\tscan_id INTEGER NOT NULL, \n\tfingerprint JSON NOT NULL, \n\tdata_origin TEXT NOT NULL, \n\trecorded_size_bytes INTEGER, \n\tsize_bytes INTEGER, \n\tsize_checked_at TEXT, \n\tCONSTRAINT pk_datasets PRIMARY KEY (dataset_id), \n\tCONSTRAINT ck_datasets_identity CHECK (length(dataset_id) > 0 AND length(name) > 0), \n\tCONSTRAINT ck_datasets_origin CHECK (data_origin = 'unknown'), \n\tCONSTRAINT ck_datasets_recorded_size CHECK (recorded_size_bytes IS NULL OR recorded_size_bytes >= 0), \n\tCONSTRAINT ck_datasets_size CHECK ((size_bytes IS NULL AND size_checked_at IS NULL) OR (size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL)), \n\tCONSTRAINT fk_datasets_scan_id_dataset_scans FOREIGN KEY(scan_id) REFERENCES dataset_scans (scan_id)\n)\n\n",
    "\nCREATE TABLE dataset_entries (\n\tpath TEXT NOT NULL, \n\tdataset_id TEXT, \n\tscan_id INTEGER NOT NULL, \n\t\"view\" TEXT NOT NULL, \n\tformat TEXT, \n\tversion TEXT, \n\tname TEXT NOT NULL, \n\tdataset_roots JSON NOT NULL, \n\tprovenance_present BOOLEAN NOT NULL, \n\tfingerprint JSON NOT NULL, \n\trecorded_size_bytes INTEGER, \n\tsize_bytes INTEGER, \n\tsize_checked_at TEXT, \n\taria2_count INTEGER, \n\tincomplete_count INTEGER, \n\tCONSTRAINT pk_dataset_entries PRIMARY KEY (path), \n\tCONSTRAINT ck_dataset_entries_identity CHECK (length(path) > 0 AND length(name) > 0), \n\tCONSTRAINT ck_dataset_entries_location CHECK ((view = 'task' AND format IS NULL AND version IS NULL) OR (view = 'format' AND format IS NOT NULL AND ((format = 'lerobot' AND version IS NOT NULL AND length(version) > 0) OR (format IN ('mcap','archives') AND version IS NULL)))), \n\tCONSTRAINT ck_dataset_entries_provenance CHECK (provenance_present IN (0,1)), \n\tCONSTRAINT ck_dataset_entries_recorded_size CHECK (recorded_size_bytes IS NULL OR recorded_size_bytes >= 0), \n\tCONSTRAINT ck_dataset_entries_size CHECK ((size_bytes IS NULL AND size_checked_at IS NULL AND aria2_count IS NULL AND incomplete_count IS NULL) OR (size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL AND aria2_count IS NOT NULL AND aria2_count >= 0 AND incomplete_count IS NOT NULL AND incomplete_count >= 0)), \n\tCONSTRAINT fk_dataset_entries_dataset_id_datasets FOREIGN KEY(dataset_id) REFERENCES datasets (dataset_id) ON DELETE CASCADE, \n\tCONSTRAINT fk_dataset_entries_scan_id_dataset_scans FOREIGN KEY(scan_id) REFERENCES dataset_scans (scan_id)\n)\n\n",
    "\nCREATE TABLE dataset_documents (\n\tentry_path TEXT NOT NULL, \n\tname TEXT NOT NULL, \n\tpayload JSON, \n\tschema_version INTEGER, \n\tsha256 TEXT, \n\tCONSTRAINT pk_dataset_documents PRIMARY KEY (entry_path, name), \n\tCONSTRAINT ck_dataset_documents_name CHECK (name IN ('原始路径.json','数据集信息.json','子任务.json')), \n\tCONSTRAINT ck_dataset_documents_schema_version CHECK (schema_version IS NULL OR schema_version = 1), \n\tCONSTRAINT ck_dataset_documents_sha256 CHECK (sha256 IS NULL OR (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*')), \n\tCONSTRAINT fk_dataset_documents_entry_path_dataset_entries FOREIGN KEY(entry_path) REFERENCES dataset_entries (path) ON DELETE CASCADE\n)\n\n",
    "\nCREATE TABLE dataset_links (\n\tentry_path TEXT NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tname TEXT NOT NULL, \n\tsource_path TEXT NOT NULL, \n\tsource_type TEXT NOT NULL, \n\tderived_entry_path TEXT NOT NULL, \n\tobserved_target TEXT, \n\tstorage_root_name TEXT, \n\tstatus TEXT NOT NULL, \n\tchecked_at TEXT, \n\tsize_bytes INTEGER, \n\tsize_checked_at TEXT, \n\tCONSTRAINT pk_dataset_links PRIMARY KEY (entry_path, ordinal), \n\tCONSTRAINT ck_dataset_links_identity CHECK (ordinal >= 0 AND length(name) > 0), \n\tCONSTRAINT ck_dataset_links_status CHECK (status IN ('unchecked','available','missing','broken','offline','mismatch','unregistered')), \n\tCONSTRAINT ck_dataset_links_checked CHECK ((status = 'unchecked' AND checked_at IS NULL) OR (status != 'unchecked' AND checked_at IS NOT NULL)), \n\tCONSTRAINT ck_dataset_links_size CHECK ((size_bytes IS NULL AND size_checked_at IS NULL) OR (size_bytes IS NOT NULL AND size_bytes >= 0 AND size_checked_at IS NOT NULL)), \n\tCONSTRAINT fk_dataset_links_entry_path_dataset_entries FOREIGN KEY(entry_path) REFERENCES dataset_entries (path) ON DELETE CASCADE\n)\n\n",
    "\nCREATE TABLE dataset_sources (\n\tentry_path TEXT NOT NULL, \n\tordinal INTEGER NOT NULL, \n\tsource_id TEXT NOT NULL, \n\toriginal_path TEXT NOT NULL, \n\tdirect_path TEXT NOT NULL, \n\tderived_entry_path TEXT NOT NULL, \n\tformat TEXT, \n\tversion TEXT, \n\tvalidation_status TEXT, \n\tstorage_root_name TEXT, \n\tstatus TEXT NOT NULL, \n\tchecked_at TEXT, \n\trobot_type TEXT, \n\tfps FLOAT, \n\tfps_rounded INTEGER, \n\tcodebase_version TEXT, \n\tmeta_checked_at TEXT, \n\tCONSTRAINT pk_dataset_sources PRIMARY KEY (entry_path, ordinal), \n\tCONSTRAINT ck_dataset_sources_identity CHECK (ordinal >= 0 AND length(source_id) > 0), \n\tCONSTRAINT ck_dataset_sources_status CHECK (status IN ('unchecked','available','missing','offline','unregistered')), \n\tCONSTRAINT ck_dataset_sources_checked CHECK ((status = 'unchecked' AND checked_at IS NULL) OR (status != 'unchecked' AND checked_at IS NOT NULL)), \n\tCONSTRAINT ck_dataset_sources_fps CHECK ((fps IS NULL AND fps_rounded IS NULL) OR (fps IS NOT NULL AND fps > 0 AND fps < 1e308 AND fps_rounded IS NOT NULL AND fps_rounded >= 0)), \n\tCONSTRAINT fk_dataset_sources_entry_path_dataset_entries FOREIGN KEY(entry_path) REFERENCES dataset_entries (path) ON DELETE CASCADE\n)\n\n",
)
_INDEX_DDL = (
    "CREATE UNIQUE INDEX ix_dataset_scans_current ON dataset_scans (is_current) WHERE is_current = 1",
    'CREATE INDEX ix_dataset_findings_panel ON dataset_findings ("group", severity, rule)',
    "CREATE INDEX ix_dataset_findings_scan_id ON dataset_findings (scan_id)",
    "CREATE INDEX ix_datasets_name ON datasets (name, dataset_id)",
    "CREATE INDEX ix_datasets_scan_id ON datasets (scan_id)",
    "CREATE INDEX ix_dataset_entries_dataset_id ON dataset_entries (dataset_id)",
    "CREATE INDEX ix_dataset_entries_scan_id ON dataset_entries (scan_id)",
    'CREATE INDEX ix_dataset_entries_tree ON dataset_entries ("view", format, version, name)',
    "CREATE INDEX ix_dataset_links_status ON dataset_links (status, entry_path)",
    "CREATE INDEX ix_dataset_sources_fps ON dataset_sources (fps_rounded, entry_path)",
    "CREATE INDEX ix_dataset_sources_identity ON dataset_sources (source_id, entry_path)",
    "CREATE INDEX ix_dataset_sources_robot ON dataset_sources (robot_type, entry_path)",
)
