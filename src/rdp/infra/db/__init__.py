"""基础层数据库包（M0 工单 05，ADR 0002/0005/0006）。

连接与事务在 connection，UTC 类型在 utc，唯一表元数据在 models，报错读写在 records，
迁移入口在 migration。只管理状态目录里的 SQLite，不访问导航层、存储根或 Web 框架。
复用 sqlite3、SQLAlchemy、Alembic、fcntl；不自行实现数据库、迁移图或文件锁。
本包不记录日志，四类异常由接口、作业或运维边界统一报告。
"""
