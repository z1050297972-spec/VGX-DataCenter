"""数据库基础层共享连接预算；不配置连接或读取环境。"""

# 工单 05 连接要求：SQLite 等待写锁的上限，单位毫秒；不额外自动重试。
BUSY_TIMEOUT_MS = 5000

# F1 的状态目录内固定相对位置；只由本模块管理，目录权限复用 STATE_DIRECTORY_MODE。
BACKUPS_DIRECTORY_NAME = "backups"
# 备份名由 uuid4().hex 生成；独立约束小写、版本位和 variant 位，与请求编号无关。
BACKUP_UUID_HEX_PATTERN = r"[0-9a-f]{12}4[0-9a-f]{3}[89ab][0-9a-f]{15}"
# F1：只识别平台生成的 UTC 时间戳、revision 和 uuid 后缀，避免清理人工备份。
BACKUP_FILENAME_PATTERN = (
    r"rdp-before-[0-9]{8}T[0-9]{12}Z-[A-Za-z0-9_]+-" + BACKUP_UUID_HEX_PATTERN + r"\.sqlite3"
)
