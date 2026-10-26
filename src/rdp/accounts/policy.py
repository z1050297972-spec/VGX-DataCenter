"""账号领域的具名边界（06 G1-G3），不读配置、时钟、数据库或生成秘密。"""

from datetime import timedelta

from rdp.infra.actors import DISPLAY_NAME_MAX_CHARS as DISPLAY_NAME_MAX_CHARS

# 登录名是稳定的机器标识；不折叠大小写、不修剪空白，避免两个输入暗中指向同一账号。
LOGIN_NAME_PATTERN = r"^[a-z][a-z0-9_.-]{2,31}$"
LOGIN_NAME_MIN_CHARS = 3
LOGIN_NAME_MAX_CHARS = 32
# G3 最少 10 个 Unicode 码点；128 上限限制哈希输入，不做组合要求或 Unicode 归一化。
PASSWORD_MIN_CHARS = 10
PASSWORD_MAX_CHARS = 128
# G1 的一天固定为 UTC 24 小时；没有绝对有效期。
SESSION_IDLE_TIMEOUT = timedelta(days=7)
# 每次请求都验证会话；正常持久化最多提前不足 60 秒过期，BUSY 跳过刷新时仍按旧活动时刻到期。
SESSION_TOUCH_INTERVAL = timedelta(seconds=60)
# 活动刷新是尽力而为的附属写入，独立连接的 BEGIN IMMEDIATE 最多等 100 毫秒，不拖住正常读取。
SESSION_TOUCH_LOCK_TIMEOUT_MS = 100
# 256 位随机令牌，不是人选口令；SHA-256 可抗穷举且不需 Argon2 的资源成本。
SESSION_TOKEN_BYTES = 32
# 这里只声明令牌格式，不含任何可用的凭据。
SESSION_TOKEN_PATTERN = r"^[A-Za-z0-9_-]{43}$"  # noqa: S105  # 理由：校验正则，不是硬编码令牌。
SESSION_DIGEST_HEX_LENGTH = 64
# G2：第五次失败起等待 60 秒；等待截止时刻恰相等时允许重试。
LOGIN_FAILURE_LIMIT = 5
LOGIN_WAIT = timedelta(minutes=1)
# 限制进程内所有 PasswordCodec 实例的 Argon2 峰值，包含初始化、假验证和成功后的重哈希。
ARGON2_MAX_CONCURRENCY = 2
# 标准库信号量最多排队 1 秒；容量不足按 ExternalError 拒绝，不算错口令、不自动重试。
ARGON2_QUEUE_TIMEOUT_S = 1.0
# 列表最多一页 100 个，按内部编号游标翻页，避免全量载入。
ACCOUNT_PAGE_LIMIT = 100
# 内部编号上限与 SQLite INTEGER 一致；公开 JSON 使用十进制字符串，防止 JS 精度丢失。
# 口令哈希仅接受本平台生成的 Argon2id 编码；限制损坏行对验证资源的影响。
PASSWORD_HASH_MAX_CHARS = 512

# 每账号最多 32 个并存会话，超出按创建时间淘汰最旧，限制重复登录的存储增长。
ACCOUNT_SESSION_LIMIT = 32
# Argon2id 存量编码的验证成本上限；256 MiB、10 轮、16 路，覆盖本票默认参数及合理旧参数。
MAX_ARGON_MEMORY_KIB = 262144
MAX_ARGON_TIME_COST = 10
MAX_ARGON_PARALLELISM = 16
