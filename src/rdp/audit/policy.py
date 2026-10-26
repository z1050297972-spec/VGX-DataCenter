"""日志领域的容量及保留期边界（07/H1），不读配置、数据库或时钟。"""

# H1 批准的共同保留期，单位 UTC 24 小时日；未设置时只读返回默认值。
MIN_RETENTION_DAYS = 7
MAX_RETENTION_DAYS = 365
DEFAULT_RETENTION_DAYS = 30
# 与账号列表相同，每页最多 100 项，限制单次查询、显示和存在性查询的内存。
AUDIT_PAGE_LIMIT = 100
# 版本、时刻、64 位编号及筛选摘要的 base64url 游标上限，单位 ASCII 字符。
AUDIT_CURSOR_MAX_CHARS = 512
# 失败补记、未知账号登录的独立写事务，BEGIN 最多等待 100 毫秒，不重试。
AUDIT_SHORT_LOCK_TIMEOUT_MS = 100
# 明细 v1 是 before/after 两个白名单对象；M1 扩展必须提升版本或保持兼容。
DETAILS_VERSION = 1
# UTF-8 编码后明细的硬上限，单位字节；本票账号及设置字段远小于 16 KiB。
MAX_DETAILS_BYTES = 16384
# 补记失败只允许这个固定标记穿过账号脱敏边界；第二异常文本及原始 notes 均禁止复制。
AUDIT_APPEND_FAILED = "AUDIT_APPEND_FAILED"
