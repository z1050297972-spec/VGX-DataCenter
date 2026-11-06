"""作业领域的容量、周期和等待预算（M0/08）；不读取配置或创建全局登记表。"""

# J3 与前端轮询一致，单位秒；09 按每类型的容量领取。
WORKER_POLL_INTERVAL_S = 1.0
# 工单心跳每 5 秒写一次，超过 15 秒视为离线；跨进程判定使用 UTC。
HEARTBEAT_INTERVAL_S = 5.0
WORKER_OFFLINE_AFTER_S = 15.0
# 进度每秒最多一次；短锁 100 毫秒与 06/07 预算一致，不占满普通 5 秒锁等待。
PROGRESS_INTERVAL_S = 1.0
PROGRESS_LOCK_TIMEOUT_MS = 100
# ADR 0005：进程组先 TERM，10 秒仍存活则 KILL；再收尾最多 2 秒。
PROCESS_TERM_GRACE_S = 10.0
PROCESS_REAP_TIMEOUT_S = 2.0
# 执行函数每个不可打断步骤至多 1 秒；停止包含 TERM/KILL、线程回收与数据库收尾。
JOB_CHECKPOINT_MAX_S = 1.0
WORKER_STOP_TIMEOUT_S = 30.0
OUTPUT_JOIN_TIMEOUT_S = 2.0
# 退出码供第 11 张命令使用；锁竞争与其他启动/运行故障可区分。
WORKER_EXIT_OK = 0
WORKER_EXIT_FAILURE = 1
WORKER_EXIT_ALREADY_RUNNING = 2
# 单页与游标有界；64 位编号通过 API 以文本传递，避免浏览器精度损失。
JOB_PAGE_LIMIT = 100
JOB_CURSOR_MAX_CHARS = 512
# 显示名 40 码点加空格、#、19 位编号不超过审计对象名 64 码点。
JOB_DISPLAY_NAME_MAX_CHARS = 40
JOB_TYPE_MAX_CHARS = 64
JOB_TEXT_MAX_CHARS = 256
# M1.5-13：中文多行子任务随参数提交，统一允许最多 1 MiB 的 UTF-8 JSON。
JOB_PARAMETERS_MAX_BYTES = 1024 * 1024
# 日志头配置和参数展示各保留 16 KiB 预算，避免触发过程消息的 64 KiB 上限。
JOB_LOG_HEADER_VALUE_MAX_BYTES = 16384
# 日志尾部最多读 64 KiB，再取最后 50 行；stderr 故障摘要只保留最后 20 行。
JOB_LOG_TAIL_LINES = 50
JOB_LOG_TAIL_MAX_BYTES = 65536
PROCESS_STDERR_TAIL_LINES = 20
# 单行按 16 KiB 分块写入，避免无换行工具输出无限积累；原始字节完整写文件。
PROCESS_OUTPUT_CHUNK_BYTES = 16384
PROCESS_STDERR_TAIL_MAX_BYTES = 32768
# 示例仅作演示：至多一万步、间隔至多一分钟；零间隔可快速验证结果。
COUNT_MIN_STEPS = 1
COUNT_MAX_STEPS = 10000
COUNT_MIN_INTERVAL_MS = 0
COUNT_MAX_INTERVAL_MS = 60000

# 停止信号和子进程轮询最多延迟 50 毫秒，避免忙等并使一分钟示例等待可及时打断。
PROCESS_POLL_INTERVAL_S = 0.05
# 诊断规则组与产物均有界；组溢出另记完整总数，产物超限拒绝而非静默裁剪（规范 2.7）。
JOB_DIAGNOSTIC_GROUP_LIMIT = 100
JOB_ARTIFACT_LIMIT = 100
JOB_ARTIFACT_MAX_CHARS = 4096

# 已批准：每条作业至多获得三次自动续跑/重跑资格；第四次改标记中断，不随成功上报归零。
JOB_RECOVERY_LIMIT = 3
# 执行函数60秒仍未响应取消时仅警告一次；从本实例首次观察cancelling起用monotonic计时。
CANCEL_STALL_WARNING_S = 60.0
# 每个作业最多一个执行线程和两个输出线程；全部daemon，全部作业共用停止预算。
WORKER_OWNED_THREAD_LIMIT = 3

# 跨来源/规则的溢出样例必须保留原身份，只有该保留键允许样例的分组键不同（规范6.6）。
JOB_DIAGNOSTIC_OVERFLOW_KEY = ("平台", "诊断规则种类超过上限")

# 09：硬件核对至多五秒，输出沿用有界 stderr 尾部；不把工具卡死当成缺卡等待。
GPU_PROBE_TIMEOUT_S = 5.0
# 写锁每 50 毫秒检查一次取消；单次等待最多 300 秒，超时按资源竞争失败，可重新提交。
NAVIGATION_LOCK_POLL_S = 0.05
NAVIGATION_LOCK_TIMEOUT_S = 300.0
# 演示等待最多十分钟；锁内暂停最多十秒，不超过 worker 共用三十秒停止预算。
GPU_EXAMPLE_MAX_HOLD_S = 600
NAVIGATION_EXAMPLE_MAX_PAUSE_S = 10
# 演示文件每条 JSON 行至多 4 KiB，新值最多 256 码点，尾读有界而不加载整个文件。
NAVIGATION_EXAMPLE_LINE_MAX_BYTES = 4096
NAVIGATION_EXAMPLE_VALUE_MAX_CHARS = 256
# 登记每天规则最多 100 项；24 小时为 UTC 固定秒数，不用本地日期差来算补跑。
SCHEDULE_LIMIT = 100
SCHEDULE_CATCH_UP_AFTER_S = 86400
# 覆盖一年及闰年/跳过日期的余量；超出说明时钟或持久化状态异常，不能无限扫描。
SCHEDULE_LOOKAHEAD_DAYS = 370


# 09：资源池只做内存读写，取锁预算独立于输出线程回收，单位秒。
RESOURCE_POOL_LOCK_TIMEOUT_S = 0.1
