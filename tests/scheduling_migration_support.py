"""0005迁移的真实旧版本库夹具；样本用冻结0004列写入，避免新ORM偷偷补新列。"""

from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from sqlalchemy import Connection, Engine, text

from rdp.infra.config import PlatformConfig
from rdp.infra.db.connection import create_database_engine
from rdp.infra.db.migration import migration_config
from rdp.infra.state import StatePaths, initialize_state, state_paths

# 已知排队样本只写旧版必填列，不依赖当前 ORM 的默认值或字段顺序。
JOB_SQL = """INSERT INTO jobs
(job_id,type_name,display_name,parameters,submitter_id,submitter_name,submitted_at,state,recovery_mode,
 total_items,failed_items,warning_count,aborted,elapsed_s,artifacts,diagnostics)
VALUES (:id,'example_count','示例：数数','{"steps": 4,"interval_ms": 0}',7,'历史提交人',
'2026-10-26T12:00:00.000000Z','queued','interrupt',0,0,0,0,0,'[]','[]')"""
OPERATION_SQL = """INSERT INTO operation_logs
(log_id,occurred_at,actor_id,actor_name,operation,object_kind,object_id,object_name,result,details)
VALUES (:id,'2026-10-26T12:00:00.000000Z',7,'历史提交人','submit_job','job','71','示例：数数 #71',
'success','{"version": 1,"before":{},"after":{}}')"""


@contextmanager
def version_four(root: Path) -> Generator[tuple[Engine, StatePaths]]:
    """真实升级到0004并插入两种历史行，退出关闭全部连接和引擎。"""
    paths = state_paths(PlatformConfig(state_dir=root), ())
    initialize_state(paths)
    engine = create_database_engine(paths.database)
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), "0004_jobs_worker")
            connection.execute(text(JOB_SQL), {"id": 71})
            connection.execute(text(OPERATION_SQL), {"id": 51})
        yield engine, paths
    finally:
        engine.dispose()


def schema_objects(connection: Connection) -> tuple[tuple[object, ...], ...]:
    """读取DDL公开边界作为迁移回滚的独立观察，不读取内部实现函数。"""
    return tuple(
        tuple(row)
        for row in connection.execute(
            text(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
            )
        )
    )
