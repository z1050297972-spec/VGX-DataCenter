"""作业领域的容量、周期和等待预算（M0/08）；不读取配置或创建全局登记表。"""

# J3 与前端轮询一致，单位秒；第 9 张再加入各类并发和资源调度。
WORKER_POLL_INTERVAL_S = 1.0
WORKER_CONCURRENCY = 1
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
JOB_PARAMETERS_MAX_BYTES = 16384
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
# 框架同时最多一个执行线程和两个输出线程；全部daemon，保留活线程才能决定是否释放实例锁。
WORKER_OWNED_THREAD_LIMIT = 3
