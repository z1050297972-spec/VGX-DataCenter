# SQLite 任务队列替代“作业表 + worker”调研报告

**结论：对本次核对的六份发布源码，不建议用其中任何一个替代平台自己的作业表与 worker。** `SQLiteAckQueue` 能省掉基本的持久化投递与确认代码；DBOS 能提供更完整的持久工作流。但在保留 R1–R12 的前提下，两者都没有显示出明显减少总代码和维护负担的优势。litequeue 0.14 则存在直接的同库限制。[S2][S7][S9][S12][S14][S16–S18]

**核验限制：本次联网搜索和页面打开均未返回可读内容。** 因此，不能确认截至 **2026 年 10 月 22 日** 的 PyPI 最新版本、发布日期、最近提交、issue 处理情况，以及 APScheduler 4.x 当前是否仍只有预发布。以下行为结论依据用户提供的发布源码；不会把本地版本冒充最新版本。没有本地源码的候选，其核验缺口单独列出。

## 0. 方法与判定口径

本次只读取文件，没有执行发布包代码，没有 import、安装依赖、运行测试或修改文件；没有通过 shell 联网，也没有访问用户禁止的目录。

实际检查了六份发布包中的：

- `PKG-INFO`、`pyproject.toml`、`setup.py`、许可证与 `py.typed`；
- 队列表结构、入队、领取、确认、删除与恢复代码；
- worker、调度器、执行器、退出及取消处理；
- 序列化、迁移、结果保留逻辑；
- 包内官方文档、README 与 changelog。

为避免反复写长路径，以下使用这些**本地相对路径前缀**：

| 简写 | 路径 |
|---|---|
| `H/` | `sources/huey-3.4.0/huey-3.4.0/` |
| `A3/` | `sources/apscheduler-3.11.3/apscheduler-3.11.3/` |
| `A4/` | `sources/apscheduler-4.0.0a6/apscheduler-4.0.0a6/` |
| `P/` | `sources/persist-queue-1.1.0/persist_queue-1.1.0/` |
| `L/` | `sources/litequeue-0.14/litequeue-0.14/` |
| `D/` | `sources/dbos-3.3.0/dbos-3.3.0/` |

判定遵循以下口径：

- **原生支持**：配置和公开 API 足以满足整条要求。
- **要自己补**：可以添加平台代码实现，但明确指出库实际省下什么。
- **做不到**：在保留该库通常使用模型的前提下，与要求冲突；需要绕开其调度、存储协议或修改库。
- 对 R1 严格区分“通过 SQLite 通信”和“平台作业行就是唯一提交、取消及执行记录”。另外增加一张库队列表，不能算满足原要求。
- “支持同步 API”和“库内部完全不使用异步运行时”分开说明。R12 主要按应用使用同步 SQLAlchemy 的要求评价。
- 不把单条需求中的“要自己补”理解为整个方案可行；例如 litequeue 其他功能可在外层实现，仍不能消除 R12 的冲突。
- 导航层写锁、冲突核对、存储根检查、文本日志和 systemd 管理不计分，只说明库可能造成的干扰。

以下是源码审查结论，不是运行验证或故障注入结果。

## 1. 各库速览

### 1.1 版本、许可证、依赖与类型标注

表中版本均为**实际检查的发布版本，未确认是最新版本**。依赖列是 Python 3.12、同步 SQLite 用法的直接运行时依赖；没有安装或求解完整传递依赖图。

| 库及检查版本 | PyPI 最新版本／发布日期 | 许可证 | 本任务用法的直接运行时依赖 | `py.typed` |
|---|---|---|---|---|
| Huey 3.4.0，`SqliteHuey` | 未确认 | MIT | 基础 SQLite 用法无第三方运行时依赖；启用 `huey[stats]` 增加 `peewee>=3.17` | 发布源码未见 |
| APScheduler 3.11.3 | 未确认 | MIT | `tzlocal>=3.0`；SQLAlchemy jobstore 需要 `sqlalchemy>=1.4`，现有 SQLAlchemy 2 可满足 | 发布源码未见 |
| APScheduler 4.0.0a6 | 未确认 | MIT | `anyio~=4.0`、`attrs>=22.1`、`tenacity>=8,<10`、`tzlocal>=3`；SQLAlchemy extra 为 `sqlalchemy[asyncio]>=2.0.24` | 有 |
| persist-queue 1.1.0，`SQLiteAckQueue` | 未确认 | BSD-3-Clause | 同步 SQLite、默认 pickle 或内置 JSON 序列化不需要第三方运行时依赖；不需要 `[async]` | 有 |
| litequeue 0.14 | 未确认 | MIT | 无第三方运行时依赖；要求 Python ≥3.12 | 发布源码未见；代码有注解 |
| DBOS 3.3.0 | 未确认 | MIT | `pyyaml>=6.0.2`、`python-dateutil>=2.9.0.post0`、`croniter>=6.2.4`、`psycopg[binary]>=3.1`、`click>=8.1`、`sqlalchemy[asyncio]>=2.0.43` | 有 |

依据：[S1][S6][S8][S11][S13][S15]。

两个容易误判的地方：

1. **DBOS 使用 SQLite 也会安装 `psycopg[binary]`**，因为它是必选依赖；这不等于必须运行 PostgreSQL 服务。同步 SQLite 可以不安装其 `aiosqlite` extra。[S15][S16]
2. **有 `py.typed` 不等于 basedpyright strict 无需适配**。例如 persist-queue 的载荷 API、DBOS 的任务参数仍使用 `Any`；边界验证和类型化包装仍有价值。[S11][S12][S16]

### 1.2 维护状态与 APScheduler 4.x 发布状态

| 库 | 本地可确认的信息 | 不能据此确认的信息 |
|---|---|---|
| Huey | 3.4.0 changelog 包含退出信号、SQLite 索引、轮询与统计修复 | 最近提交日期、当前 issue 响应速度 |
| APScheduler 3.x | 3.11.3 changelog 明确记录修复 #1103、#1119 | 修复发布日期及当前维护活跃度 |
| APScheduler 4.0.0a6 | 该发布包 README 明确标为预发布，并警告不要用于生产 | 截至当前是否已有后续 alpha、beta 或正式版 |
| persist-queue | 1.1.0 文档包含新增异步队列等变更 | 当前发布节奏、issue 是否持续处理 |
| litequeue | README 记录 0.13、0.14 的领取保护、时间戳与迁移变更 | 当前提交及 issue 活跃度 |
| DBOS | 3.3.0 metadata 声明 Production/Stable，源码包含 SQLite 实现 | 近期维护活动；metadata 不能替代维护调查 |

依据：[S1][S6][S8][S11][S13][S15]。

**能够确认的是“4.0.0a6 本身是预发布”；不能确认“APScheduler 4.0 截至 2026 年 10 月 22 日仍是预发布”。** 两句话不能混用。[S8]

## 2. 各库 R1–R12 对照

### 2.1 Huey 3.4.0：`SqliteHuey`

Huey 提供独立 consumer、执行并发、重试和周期调度，但 SQLite 中的 `task` 表是待投递消息表。**任务领取时会删除该行**，它不能直接成为永久的平台作业记录。[S2][S4]

| 需求 | 判定 | 理由与需要补的内容 |
|---|---|---|
| R1 | **做不到** | 独立 consumer 和 SQLite 轮询可用，但领取会删除 `task` 行，撤销写到 `kv`，不符合提交、取消和执行一直围绕同一平台作业行的协议。另建平台账本及桥接会改变该协议。[S2][S3] |
| R2 | **要自己补** | 执行信号、结果和错误不是要求的六态；需完整业务状态机、四种完成结果与计数规则。[S3] |
| R3 | **要自己补** | 核心队列不持久保留运行中标记。需在自己的账本记录执行者、阶段和进度，启动扫描后分类恢复，并建立导航恢复屏障。[S2–S5] |
| R4 | **要自己补** | `revoke()` 主要阻止尚未开始的任务，不能停止正在运行的函数。取消请求、子进程停止、十秒升级与关键步骤保护均由平台做。[S3] |
| R5 | **要自己补** | consumer 的 `workers` 是全局并发；`lock_task` 是领取后的互斥，不是按类型在领取前分配名额。需类型准入调度，避免已满类型占用执行位。[S3][S4] |
| R6 | **要自己补** | 没有 GPU 分配器；需在派发前分配卡号，结束后归还。[S4] |
| R7 | **要自己补** | 没有所需阶段、计数、更新时间和限频模型；需要自己的持久进度接口。[S2][S3] |
| R8 | **要自己补** | consumer 的内部 worker 健康检查不是数据库中供 Web 查询的心跳；需另写。[S4] |
| R9 | **要自己补** | Huey 任务锁不能替代 worker 实例的排他文件锁；需外层 `fcntl.flock`。[S3][S4] |
| R10 | **要自己补** | 周期触发和入队原生具备；但必须补“系统”提交人及统一的平台作业创建路径。[S4] |
| R11 | **要自己补** | 队列行会删除，结果读取默认可以消费并删除结果；统计模块也不是永久账本。全部业务档案需另存。[S2][S3][S5] |
| R12 | **要自己补** | 可指定现有 SQLite 文件、同步使用并配置 WAL；支持 `create_tables=False`。可以由 Alembic 预建兼容表，但其存储使用自己的 sqlite3 连接和事务，不参加平台 Session。[S2] |

**不能把 `huey.contrib.stats` 当成 R3 的可靠替代。** 它确实有持久的 `HueyInflight`，但事件先缓冲再异步写入，写失败会丢弃；默认还会清理历史和超时 inflight。该模块适合观测，不是执行前必须落盘的恢复账本，且额外引入 Peewee。[S5]

### 2.2 APScheduler 3.11.3：SQLAlchemy jobstore

3.x 的 `jobstore` 主要保存未来调度计划。它不是带领取确认和运行记录的永久任务队列。[S7]

| 需求 | 判定 | 理由与需要补的内容 |
|---|---|---|
| R1 | **做不到** | 官方包内 FAQ 明确不支持多个进程共享 jobstore 并保证正确同步、唤醒；推荐的远程调用方案又违反本任务约束。另写每秒轮询平台表的循环，实际已经绕开 jobstore 调度模型。[S7] |
| R2 | **要自己补** | SQLAlchemy 表只有 `id`、`next_run_time`、`job_state`；六态与业务结果必须另存。[S7] |
| R3 | **要自己补** | 单次任务提交 executor 后即可删行，没有持久 running/ack 标记；需自己的执行账本及全部分类恢复逻辑。[S7] |
| R4 | **要自己补** | 删除或暂停 job 不能取消已运行函数；需平台取消协议及子进程监督。[S7] |
| R5 | **要自己补** | `max_instances` 按 job ID 计数，不是按业务类型；达到上限会跳过该次触发，不保证留队等待。需自己的持久队列与准入层。[S7] |
| R6 | **要自己补** | GPU 名额、环境变量、释放均由平台做。[S7] |
| R7 | **要自己补** | 无业务进度模型，需自己的记录和一秒限频。[S7] |
| R8 | **要自己补** | 无符合要求的 worker 数据库心跳。[S7] |
| R9 | **要自己补** | 外层文件锁。[S7] |
| R10 | **要自己补** | cron、interval 等时间计算原生具备；触发后创建“系统”作业及统一审计记录仍需平台函数。[S7] |
| R11 | **要自己补** | 单次 job 自动移除，没有永久作业结果账本；需另存全部详情及重提关系。[S7] |
| R12 | **要自己补** | 同步 SQLAlchemy、SQLite、传入 Engine/MetaData 可用；可在 Alembic 预建兼容表，但库启动仍会 `create(checkfirst=True)`，写入也自行开启事务。[S7] |

**合理的有限用途**是把它放在 worker 内，仅用于到点调用平台 `submit_job()`。这能省掉复杂日历调度代码，不能替代作业系统。[S7]

### 2.3 APScheduler 4.0.0a6：SQLAlchemy datastore

4.x 将 task、schedule、job、job result 分开，增加领取者、租约和 task 级并发控制。它比 3.x 更接近任务队列，但不能直接套用 3.x 的存储或运行结论。[S8–S10]

| 需求 | 判定 | 理由与需要补的内容 |
|---|---|---|
| R1 | **做不到** | 官方跨进程模型依赖共享 event broker；本地 broker 不跨进程。worker 等待 `JobAdded`/`JobReleased` 唤醒，不是每秒兜底查库。源码还明确警告不要用 SQLite 供多个 scheduler 共享。[S8–S10] |
| R2 | **要自己补** | 有领取信息和 outcome，但不是业务六态、四种完成结果，需平台账本。[S9] |
| R3 | **要自己补** | 有租约和 abandoned 处理，但没有最后进度、三种恢复策略或导航恢复屏障；结果清理前也必须保留平台诊断。[S9][S10] |
| R4 | **要自己补** | 调度器停止、协程取消不等于同行取消请求，更不负责 CLI 的 TERM→十秒→KILL；同步任务仍须平台协作取消。[S10] |
| R5 | **要自己补** | `Task.max_running_jobs` 原生按 task 限并发，默认 1；但该版 SQLAlchemy 后端先 `LIMIT` 再跳过无名额类型，不能保证其他类型不被队首挡住。[S9] |
| R6 | **要自己补** | 需 GPU 资源准入与卡号分配。[S9] |
| R7 | **要自己补** | 无要求的持久业务进度及节流 API。[S9] |
| R8 | **要自己补** | 作业租约续期不等于闲置 worker 也会更新的在线心跳；需另写。[S9][S10] |
| R9 | **要自己补** | 外层文件锁。[S10] |
| R10 | **要自己补** | schedule 生成 job 原生具备；“系统”提交人和永久平台记录仍需适配。[S8][S9] |
| R11 | **要自己补** | 完成后删除 jobs 行；结果默认保留时长为 0，取结果也会删除。需独立永久账本。[S9] |
| R12 | **要自己补** | 可使用同步 API 和同步 SQLAlchemy Engine；但门面内部启动 AnyIO/asyncio 事件循环，库自管 schema/version，需 Alembic 兼容层。若“不用 async”也禁止库内异步运行时，则此项应判做不到。[S9][S10] |

R5 的判断是源码推论：假设全局还剩一个执行位，最老任务属于已满的类型 A，类型 B 排在后面。SQL 查询先只取一行，随后跳过 A，本轮就不会检查 B。不能仅看到 `max_running_jobs` 就把整条 R5 判为原生支持。[S9]

### 2.4 persist-queue 1.1.0：`SQLiteAckQueue`

这是一个**持久队列容器**，没有现成的 worker 执行服务。它最有价值的能力是领取后保留 `unack`，并提供显式确认与重投。[S12]

| 需求 | 判定 | 理由与需要补的内容 |
|---|---|---|
| R1 | **做不到，按严格单行协议** | 可通过 SQLite 在进程间投递，但公开模型只有序列化载荷和投递状态，没有平台同行取消协议。需要接管、扩展其私有表，或另加平台作业表；常见“平台 jobs + AckQueue”方案不满足原 R1。[S12] |
| R2 | **要自己补** | `inited/ready/unack/acked/ack_failed` 是投递状态，不是业务六态；需业务状态、结果和计数，不能只改枚举名称。[S12] |
| R3 | **要自己补** | `unack` 提供识别基础；但默认打开队列就全量重投，不区分作业类型。必须关闭自动恢复，先记录中断，再分类恢复及执行导航恢复屏障。[S12] |
| R4 | **要自己补** | 没有执行器、子进程或取消机制；全部 R4 逻辑由自己的 worker 实现。[S12] |
| R5 | **要自己补** | 无类型并发调度。按类型分队列或自己选择可运行任务，配额、执行池和公平性仍需平台实现。[S12] |
| R6 | **要自己补** | GPU 名额及任务准入自己实现。[S12] |
| R7 | **要自己补** | `update()` 可以替换载荷，但无阶段、计数和限频；整块载荷覆盖还可能丢失并发写入的取消请求。[S12] |
| R8 | **要自己补** | 自建 worker 心跳。[S12] |
| R9 | **要自己补** | 内部 `threading.Lock` 不等于跨进程文件锁。[S12] |
| R10 | **要自己补** | 没有定时调度器，需时间计算、去重和系统提交记录。[S12] |
| R11 | **要自己补** | `ack()` 标记而不删除；不调用清理可以留消息，但完整档案、诊断、血缘和重提关系仍需自己建模。[S12] |
| R12 | **要自己补** | 可通过目录及 `db_file_name` 指向业务数据库，同步 sqlite3 并启用 WAL；没有 SQLAlchemy/Alembic 集成，自动建表也没有公开禁用开关，需要维护兼容 schema。[S12] |

若接受直接扩展队列表、增加自己的列及 SQL 访问层，可以把 R1 的实现问题转化为“自己补”；但此时平台已经接管了核心作业协议，而库省掉的主要仍是几条投递状态操作。

必须注意两个默认行为：

- **所有普通客户端都应显式 `auto_resume=False`。** 否则 Web 重启、重新构造队列对象，也会把当前 worker 正在执行的 `unack` 改回 `ready`，造成重复执行。[S12]
- 默认阻塞 `get()` 使用进程内事件，跨进程等待的轮询间隔可达十秒；`qsize()/empty()` 又使用本地缓存。要满足一秒响应，宜自行非阻塞查库，不能依赖另一个进程更新该缓存。[S12]

### 2.5 litequeue 0.14

**该版本明确拒绝与其他应用表共用数据库。** 初始化检查 `sqlite_schema`，发现除 `Queue` 外的非 SQLite 内部表就抛异常；业务表和 `alembic_version` 都会触发。这是 R12 的硬冲突。[S14]

| 需求 | 判定 | 理由与需要补的内容 |
|---|---|---|
| R1 | **做不到，按严格单行协议** | 有 SQLite 投递、没有 worker；公开接口没有平台同行取消请求和完整作业记录更新协议，需自写访问层或另建表，后者又受同库限制。[S14] |
| R2 | **要自己补** | 只有 `READY/LOCKED/DONE/FAILED`；业务六态、四种结果和进度仍需自己建模。[S14] |
| R3 | **要自己补** | 保留 `LOCKED`、`lock_time`、`claim_id`；通常不会自动重投。分类恢复、日志和导航恢复屏障由平台实现。[S14] |
| R4 | **要自己补** | 没有任务执行层取消；全部 CLI 控制和关键步骤保护自己做。[S14] |
| R5 | **做不到，按现有共库约束** | `pop()` 领取最老 READY，没有按类型过滤；`maxsize` 是容量。分数据库分类型违反 R12，在单队列按资源择取则须绕开其 FIFO 领取接口。[S14] |
| R6 | **要自己补** | 无 GPU 分配器。[S14] |
| R7 | **要自己补** | 时间戳和字符串载荷不提供所需实时进度模型。[S14] |
| R8 | **要自己补** | 无 worker 心跳。[S14] |
| R9 | **要自己补** | 线程锁及数据库事务不是实例文件锁。[S14] |
| R10 | **要自己补** | 无定时调度器。[S14] |
| R11 | **要自己补** | 不调用 `prune()` 可以保留终态消息，但业务档案、血缘与重提关系仍需补齐。[S14] |
| R12 | **做不到** | 明确禁止其他应用表共库，自行迁移并占用全库 `PRAGMA user_version`；需要改库或独立数据库。[S14] |

它的领取与 `claim_id` 校验可以作为实现参考，但不适合本项目直接采用。[S14]

### 2.6 DBOS Transact 3.3.0

**DBOS 的 SQLite 路线是真实存在的，不能按“必须 PostgreSQL”排除。** 本版本有同步 SQLite 系统数据库和轮询通知实现；Conductor 网络连接按配置启用，不是 SQLite 本地运行的必需服务。[S16][S17]

它解决的是持久工作流与步骤重放，能力明显多于基本队列；代价是引入另一套生命周期、迁移和恢复语义。[S16–S18]

| 需求 | 判定 | 理由与需要补的内容 |
|---|---|---|
| R1 | **做不到，按严格单行协议** | 独立 producer/worker、SQLite 通信可行；但入队与执行使用 DBOS workflow/step 内部表和 API，取消直接写其终态，并非平台单行取消请求协议。[S16][S17] |
| R2 | **要自己补** | 内置 `PENDING/SUCCESS/ERROR/CANCELLED/ENQUEUED/DELAYED` 等状态不等于要求的六态；需要自己的业务状态、计数及完成结果。[S17] |
| R3 | **要自己补** | 能自动恢复匹配的 `PENDING` 并复用已记录步骤结果；但三种恢复策略、最后进度、中断日志、转换禁止重跑和导航恢复屏障仍须平台控制。[S17] |
| R4 | **要自己补** | `cancel_workflow()` 会先写 `CANCELLED`，不等待同步外部工具退出；需另外实现取消请求、正在取消、子进程监督和关键步骤保护。[S17] |
| R5 | **原生支持** | 每个类型配置一个 queue，设置 `worker_concurrency`/`global_concurrency`，平台默认设为 1；各 queue 有独立轮询。需保证总执行池容量与配置匹配。[S18] |
| R6 | **要自己补** | queue 并发不是跨类型 GPU 资源池；卡号分配、等待和归还仍需平台准入层。[S18] |
| R7 | **要自己补** | 已完成步骤结果不能代替运行中的阶段与计数；需要实时进度、限频和退出诊断。[S16][S17] |
| R8 | **要自己补** | 需本地数据库 heartbeat；Conductor 连接不等于要求的 worker 心跳。[S16][S17] |
| R9 | **要自己补** | executor ID 不是排他锁，外层仍须 `fcntl.flock`。[S17] |
| R10 | **要自己补** | cron 调度、入队原生具备；系统提交人和统一平台记录仍需接入。[S18] |
| R11 | **要自己补** | 能保存 workflow 输入输出、步骤结果等，但完整业务档案、诊断及指定重提关系仍需平台记录；不能仅凭未发现自动清理就保证所有配置永久保留。[S16][S17] |
| R12 | **要自己补** | 同库及同步 SQLAlchemy 可行，还支持调用方事务内入队；但自管 schema 和 `dbos_migrations`，需要把固定版本的迁移协调进 Alembic。[S16] |

**DBOS 有一个实际优势：** `DBOSClient.enqueue_in_transaction()` 接受同步 SQLAlchemy `Connection` 或 `Session`，能把业务记录创建与 DBOS 入队放在同一事务里。不能笼统说它必然存在提交双写窗口。但这不自动解决后续两套状态机的一致性。[S16]

## 3. worker 崩溃时，正在执行的任务会怎样

下表中的“丢失”，指库不再保有可自动恢复这次执行的队列记录，**不表示已经生成的文件会消失**。

SIGINT、SIGTERM 是信号名称，不天然等于优雅退出。必须看程序如何接收信号、是否等待任务、是否最终被强制终止。

| 库 | 受控优雅停止 | `kill -9` 等硬崩溃 | 决定行为的源码 |
|---|---|---|---|
| Huey | 默认 SIGINT 等待运行任务；默认 SIGTERM 中断。3.4.0 可配置互换，也可配置优雅等待超时。中断回调可自行重投，但不是默认可靠恢复。 | **核心队列中丢失**：领取已删行，内存 inflight 随进程消失。 | `H/huey/storage.py:952–966`；`consumer.py:294–354,470–525`；`api.py:279–286,462–516`。[S2–S4] |
| APScheduler 3.x | 应用调用 `shutdown(wait=True)` 时等待当前任务，不主动中断。 | **通常丢失该次执行**：单次任务已删；周期任务下一触发时刻已推进。 | `A3/src/apscheduler/schedulers/base.py:221–239,1191–1233`。[S7] |
| APScheduler 4.0a6 | 同步 thread executor 没有强杀函数机制；异步执行路径可以产生 cancelled outcome。具体信号桥接由应用负责。 | **留下领取标记；不是可靠自动重投保证**。启动或清理可能判 abandoned 并删行；过期项也存在再次被领取的路径。 | `A4/src/apscheduler/datastores/sqlalchemy.py:881–1009,1038–1104,1140–1211`；`_schedulers/async_.py:1118–1181`。[S9][S10] |
| SQLiteAckQueue | 库没有退出处理。完成后 ack 留 `acked`；未 ack 就退出则留 `unack`。 | **留下 `unack`；默认重新构造对象时自动重投**。关闭 `auto_resume` 后由平台决定。 | `P/persistqueue/sqlackqueue.py:63–81,168–181,212–248`。[S12] |
| litequeue | 库没有退出处理。完成并 `done()` 留 DONE，否则留 LOCKED。 | **留下 LOCKED 标记**；正常打开数据库不会自动恢复，需要显式 `retry()` 或 `retry_expired()`。 | `L/src/litequeue/__init__.py:554–615,668–818`。[S14] |
| DBOS | `destroy()` 可等待活动 workflow，但等待参数默认 0；同步运行线程不是被强制杀死。未完成工作仍需按持久状态恢复。 | **留下 PENDING，并有条件自动重投/重放**；启动恢复按 executor ID、应用版本等匹配，不是所有遗留任务无条件恢复。 | `D/dbos/_dbos.py:436–446,709–723,912–946`；`_sys_db.py:2622–2644,4464–4501,4715–4749`。[S17] |

### 3.1 几个不能省略的边界

**Huey 的失败重试不等于硬崩溃恢复。** 普通异常可以进入重试逻辑，进程被杀却不能执行异常处理；出队已经删行。`SIGNAL_INTERRUPTED` 也不能在断电后凭空运行。[S2][S3]

**APScheduler 3.x 也不能简单称为严格“最多一次”。** executor 提交与 jobstore 更新、删除不是一个原子动作。如果崩溃恰好发生在提交后、删行前，旧任务可能留下并再次执行。因此正常执行中通常失去恢复记录，并不排除边界窗口中的重复。[S7]

**APScheduler 4.0a6 的 abandoned 不等于永久中断档案。** 同 identity 启动会清理其遗留作业；过期租约清理也会产生 abandoned，但 `_release_job()` 删除 jobs 行，默认结果保留又为 0。平台不能依赖它长期展示最后阶段和计数。[S9][S10]

**SQLiteAckQueue 的自动恢复不检查 worker 是否死亡。** 它只是初始化时批量 `unack → ready`。这正是 Web 重启也可能导致重复执行的原因。[S12]

**普通 `SQLiteQueue` 与 `SQLiteAckQueue` 不同。** 前者默认 `auto_commit=True` 时在返回前删除消息；不能把 AckQueue 的崩溃恢复结论套到所有 SQLite 队列上。[S12]

**litequeue 的 claim fencing 只保护状态写回。** `claim_id` 可以拒绝旧领取者提交 DONE，但不会撤销旧外部工具已经完成的文件操作。不能仅因任务运行很久，就用 `retry_expired()` 推断其 worker 已死。[S14]

**DBOS 步骤重放仍可能重复外部副作用。** 若外部 CLI 已经写文件，但进程在步骤结果落库前崩溃，恢复时该步骤可以再次执行。它不能自动把文件系统操作变成“恰好一次”。[S17]

### 3.2 整机断电与进程被杀

以上领取状态结论针对**数据库中已经持久保存的状态**。断电后能保住最近哪笔提交，还取决于 SQLite 同步设置、文件系统及存储设备，不能仅凭队列有 WAL 就保证。

特别是 litequeue 0.14 会设置 `PRAGMA synchronous=NORMAL`；Huey 有 `fsync` 配置。平台若对“已提交作业不能因断电丢失”有明确要求，必须把耐久性设置作为数据库统一策略，而不是让各库连接各自决定。[S2][S14][S25]

## 4. 能否取消正在运行的任务

| 库 | 库提供的取消机制 | 是否原生满足完整 R4 | 对导航关键步骤的影响 |
|---|---|---|---|
| Huey | revoke 阻止未执行任务；运行函数需协作检查。consumer 中断和任务 timeout 是另一套机制。 | **否**。需自己控制 CLI、十秒升级及状态收尾。 | consumer 强制退出或配置任务 timeout 可能打断执行，不能把它们当业务取消协议。[S3][S4] |
| APScheduler 3.x | remove/pause 针对未来调度；不停止已运行函数。 | **否**。全部运行取消由平台做。 | 不会因 remove 自动安全停止子进程，也不理解关键步骤。[S7] |
| APScheduler 4.0a6 | 调度器 cancel scope、异步任务 cancellation；同步 executor 不提供强杀线程。 | **否**。没有同行取消请求及 CLI 信号升级。 | 若用异步 executor，取消可在 await 边界中断，关键区需额外保护。[S10] |
| SQLiteAckQueue | 无执行层取消；ack/nack 只改投递状态。 | **否，但自己的 worker 可实现**。 | 库不会主动杀任务，也不提供保护。[S12] |
| litequeue | 无执行层取消；retry、done、failed 只改数据库状态。 | **否，但外层可实现**；R12 冲突仍存在。 | 同上。[S14] |
| DBOS | 取消写入 CANCELLED；同步工作在操作/步骤边界检查。异步步骤另有抢占机制。 | **否**。同步步骤不支持 `preemptible=True` 或 `timeout_seconds`，更不负责外部 CLI 的 TERM/KILL。 | 不能在工具还运行时，把库的 CANCELLED 直接展示为平台“已取消”；关键段中触发取消检查也要处理。[S17] |

对本项目，R4 实际需要的是一个独立于库的子进程监督协议：

1. Web 在作业行写取消请求。
2. worker 每秒检查；排队任务直接结束，运行任务进入“正在取消”。
3. 若在导航关键步骤，先完成该步骤。
4. 允许停止后，对工具发 SIGTERM，并从这个时刻开始计算约十秒期限。
5. 仍未退出则 SIGKILL；确认子进程退出后，再写“已取消”并保留最后进度。
6. 不清理产物。

这是根据需求整理的实现建议。上述库没有一个原生提供这套完整协议。

## 5. 其他候选与排除项

### 5.1 django-q2 ORM broker

用户已指出该路线依赖 Django。对现有 FastAPI、SQLAlchemy 2、Alembic 平台，**若采用 Django ORM broker，就要额外引入 Django ORM 及其初始化、模型和迁移体系**；这与 R12 的既定数据访问和表结构管理方式存在明显整合成本，因此不建议作为首选替代路线。

本轮没有本地 django-q2 源码，联网读取也未成功，所以以下信息均为**未确认**：

- 最新版本、发布日期、许可证、运行时依赖和 `py.typed`；
- 当前 ORM broker 对 SQLite 的明确支持范围；
- 领取、ack、超时重投、优雅退出与运行取消的具体行为；
- R1–R11 的可靠逐条能力判断。

不能把其他 Django 任务队列或旧版 django-q 的行为直接套到 django-q2。官方核验入口见 [S19]。

### 5.2 Taskiq 与 SQLite broker

**本轮未确认存在可用且受维护的 Taskiq SQLite broker，也不能据此断言不存在。**

在 broker 本身没有确认之前，不能给 Taskiq 框架的执行能力直接记分，更不能把 SQLite 结果后端误当成 SQLite broker。其最新版本、依赖、许可证、类型标注，以及候选 broker 的领取确认和恢复行为均未确认。官方核验入口见 [S19]。

这两条线索的在线核验未完成，不纳入六份本地源码的比较结论。

### 5.3 按要求排除的队列

以下每项仅列排除依据和官方入口；**本次未成功读取这些在线页面，当前具体支持范围仍待复核**。

- **RQ**：其通常部署依赖 Redis/Valkey 服务，与不增加此类服务的约束不符；官方入口：[S20]。
- **arq**：其任务队列以 Redis 为基础，与不增加 Redis 的约束不符；官方入口：[S21]。
- **Celery**：按指定范围不展开，但不能把排除理由写成“只能用 Redis/RabbitMQ”，因为 Kombu 存在 SQLAlchemy transport 路线，当前 SQLite 支持质量本轮未确认，不能将其视作已验证替代方案；官方入口：[S22]。
- **Dramatiq**：其标准 broker 路线为 RabbitMQ/Redis，与本次服务约束不符；官方入口：[S23]。
- **Procrastinate**：其队列使用 PostgreSQL，与 SQLite-only 约束不符；官方入口：[S24]。

## 6. 结论与建议

### 6.1 有没有哪个库能明显减少要写的代码？

**在保持当前需求的情况下，没有。这个结论限定于已经检查的六份发布源码。**

原因并非这些库“功能不够多”，而是本项目的大部分代码位于它们的职责之外：

- 六态与四种业务结果；
- 启动时识别旧执行、保存诊断并按类型恢复；
- 外部命令的取消和终止确认；
- 导航关键步骤保护及恢复屏障；
- 类型名额与 GPU 名额联合准入；
- 进度、心跳、永久档案和血缘引用。

基本队列主要省下入队、领取、确认；Huey 增加 consumer 与定时，APScheduler 增加日历调度，DBOS 增加持久步骤重放。采用它们之后，上述平台代码仍大多需要保留，还要协调库自己的状态和恢复行为。[S2–S18]

建议：

- **继续采用平台自己的单一作业表与单实例 worker。**
- `SQLiteAckQueue` 可作为领取/确认设计参考，但不建议仅为几项 SQL 操作引入第二套投递状态。
- litequeue 0.14 因 R12 直接排除。
- APScheduler 3.x 仅在未来确有复杂日历需求时，考虑作为 worker 内部的定时触发组件。
- DBOS 是值得区分对待的候选：若未来愿意把任务改为持久工作流模型，可以重新评估；当前要求下不建议为了复用它而重写业务恢复语义。

这是基于源码差异的工程判断，没有给出未经测量的代码减少比例。

### 6.2 如果采用这些库，仍要补什么？

| 方案 | 能省下的主要部分 | 仍需平台实现的主要部分 |
|---|---|---|
| Huey | consumer、基础并发、重试、周期触发 | 永久账本、六态、崩溃识别、三策略恢复、取消、资源准入、进度、心跳、实例锁 |
| APScheduler 3.x | 日历触发、执行器包装 | 几乎整个作业管理系统 |
| APScheduler 4.0a6 | 新作业模型、租约、task 并发、调度 | 平台账本、恢复策略、取消、GPU、进度、心跳，以及跨进程通知和 SQLite 限制处理 |
| SQLiteAckQueue | 基础持久投递、未确认状态、确认/重投 | 整个 worker、业务状态、调度、取消、恢复分类、进度、心跳和永久记录模型 |
| litequeue | 领取事务、锁定记录、claim 校验 | 上述大部分平台能力；还须先解决不允许共库的冲突 |
| DBOS | 持久工作流、步骤结果复用、队列并发、定时 | 业务六态、取消监督、外部副作用恢复策略、导航屏障、GPU、进度、心跳、永久详情映射 |

依据：[S2–S18]。

### 6.3 相比自己写，新增的主要风险

**第一，两份状态事实来源。**

“库已领取”“函数已返回”“平台已完成”“工具已退出”不是同一件事。把平台 jobs 和库队列表并排放置，需要处理：

- 平台已创建作业，库消息未提交；
- 库已领取，平台还未记录 running；
- 库认为取消完成，外部工具仍在写文件；
- 库删除执行记录，平台尚未保存摘要；
- 库自动恢复，平台判定该类型必须保持中断。

DBOS 的事务内入队能解决第一类提交窗口；它不能自动解决其余生命周期差异。[S16][S17] Huey、APScheduler 3.x、persist-queue 的常见存储调用则自行管理连接或事务，需要额外协调。[S2][S7][S12]

**第二，序列化与升级耦合。**

| 库 | 检查版本的默认或主要方式 | 平台需注意 |
|---|---|---|
| Huey | pickle，可替换 serializer | 参数/结果与 Python 对象、代码版本耦合 |
| APScheduler 3.x SQLAlchemy | `job_state` 为 pickle | 不是结构化永久账本；恢复反序列化失败时还可能删除 job |
| APScheduler 4.0a6 | 默认 PickleSerializer；支持 JSON/CBOR 替换 | 必须统一 producer/worker 配置及兼容策略 |
| persist-queue | 默认 pickle；有内置 JSON serializer | 优先考虑 JSON，但仍须业务 schema 校验 |
| litequeue | 字符串 data | 可由平台用 JSON，不原生承担对象序列化 |
| DBOS | 默认 pickle + base64；可配置 serializer | base64 不改变 pickle 的对象和代码耦合 |

依据：[S3][S7–S9][S12][S14][S16]。

不应反序列化不可信 pickle。对于本平台，JSON 参数加明确的 `job_type`、参数版本和校验边界，更容易长期保存、迁移与静态检查；这是实现建议。[S25]

**第三，表结构所有权。**

- Huey 支持关闭自动建表，比较容易把兼容 DDL 纳入 Alembic。[S2]
- APScheduler 3.x 可以传 MetaData，但需要协调自动建表；4.x 另有内部 schema version。[S7][S9]
- persist-queue 自动建表，无原生 Alembic 集成，需要自己维护兼容表结构。[S12]
- litequeue 0.14 直接拒绝 `alembic_version` 等共库表。[S14]
- DBOS 有自己的 `dbos_migrations`；禁启动迁移只会转为版本校验，不意味着可以不管理其迁移。[S16]

因此，“都用 SQLite”远远不等于“表结构都自然归 Alembic”。

**第四，同库写锁竞争。**

WAL 不会让同一 SQLite 数据库同时拥有多个写事务。进度、心跳、业务索引，以及库额外的领取、确认、租约、步骤 checkpoint 和清理，都需要争用写入机会。应统一短事务、等待策略和失败处理；不能把长任务期间的数据库事务一直打开。[S2][S9][S12][S14][S16][S25]

源码能说明写入来源，不能证明本项目实际会遇到多严重的竞争；这需要后续以真实并发和进度写入频率验证。

**第五，类型检查成本。**

没有 `py.typed` 的库不一定完全无法推断类型；有 marker 的库也可能大量返回 `Any`。应把第三方调用收敛到窄接口，平台内部使用有类型的参数、进度和结果模型，而不是让不确定的载荷类型贯穿业务层。[S1][S8][S11–S16]

**第六，库升级会改变恢复语义。**

本次已有具体例子：litequeue 的单表约束及迁移逻辑、Huey 的退出信号选项、APScheduler 两代数据模型、DBOS 的版本匹配恢复。引入库后，升级审查必须覆盖这些行为，不能只验证“还能入队”。[S1][S8][S14][S17]

### 6.4 自己写需要的最小部件

这里的建议是一个服务于本平台的 worker，不是重新实现通用 Celery。

| 最小部件 | 职责 | 可直接复用 |
|---|---|---|
| 作业模型与迁移 | 参数、提交人快照、六态、取消请求、结果、进度、计数、诊断、摘要、重提来源、执行实例/尝试信息 | 已批准的同步 SQLAlchemy 2、Alembic；`enum`、`dataclasses`、`typing`、`json` |
| 状态转换接口 | 校验转换，处理领取与取消竞争，保证终态记录完整 | SQLAlchemy 条件 UPDATE、事务 |
| 单实例入口 | 启动首先拿锁；运维命令复用同一锁 | `fcntl.flock`、`os`、`pathlib` |
| 调度循环 | 每秒检查；只领取同时满足类型名额与 GPU 名额的作业；不让已满类型挡住其他类型 | `threading`、`time.monotonic`；必要时 `concurrent.futures` |
| 执行上下文 | 为任务提供阶段更新、计数、取消检查、资源和日志接口 | `dataclasses`、`typing.Protocol`、`logging` |
| 子进程监督器 | 启动工具、设置环境、收集退出信息、TERM→等待→KILL、确认退出 | `subprocess`、`signal`、`os`、`time.monotonic` |
| 启动恢复器 | 持锁后扫描旧 running/cancelling；先保存中断诊断，再按类型续跑、重跑或终止；导航恢复成功后放行写操作 | SQLAlchemy；平台已有导航恢复流程 |
| 进度写入器 | 合并进度，普通更新每秒最多一次；结束时保存最终快照；避免覆盖取消请求 | `time.monotonic`、`threading`、同步 SQLAlchemy |
| 心跳 | 独立于任务是否运行，定时更新 worker 行；网页判断过期 | `datetime`、同步 SQLAlchemy |
| 定时提交器 | 计算到期时刻，通过统一提交函数创建“系统”作业；持久去重并明确错过时刻策略 | 简单每日计划用 `datetime`、`zoneinfo`；复杂日历再评估 APScheduler |
| 永久查询与重新提交 | 保留历史；重提新建编号并关联原作业 | SQLAlchemy |

标准库 API 入口见 [S25]。这张表是设计建议，不是已实现或已验证的代码。

还应保留三个实现约束：

1. **不要先把任务交给线程池，再让线程等待类型名额或 GPU。** 应先完成资源准入，再领取并派发。
2. **领取、取消和结束使用条件更新。** 尤其不能用一整块 JSON 的覆盖写入，让进度更新抹掉 Web 刚写入的取消请求。
3. **续跑和重跑之前先保存旧尝试的诊断。** 可以在同库保留尝试历史或中断事件；作业行仍是 Web 与 worker 的提交、取消协议，不必为此增加另一套消息队列。

验证重点应放在有实际失败风险的边界：领取与取消竞争、执行中被杀、文件操作完成但结果未落库、恢复屏障失败、GPU 名额释放、取消升级以及定时重复提交。不能仅用“入队后能运行”的测试代表完整正确性。

## 7. 来源清单

**引用说明：** 上游发布 tag 本轮均未在线确认，因此不构造看似固定但未经核实的 tag 链接。下列结论以指定版本 sdist 的本地路径及行号为依据；上游网址用于定位项目。`H/` 等前缀按第 0 节展开，即为完整本地相对路径。

### 已实际读取的发布源码

**[S1] Huey 3.4.0 元数据与变更记录**

- 上游：<https://github.com/coleifer/huey>
- PyPI 核验入口：<https://pypi.org/project/huey/>
- 本地：`H/PKG-INFO:1–24`、`H/pyproject.toml`、`H/LICENSE`、`H/CHANGELOG.md:8–95`。
- 本地文件清单未见 `py.typed`。

**[S2] Huey SQLite 存储**

- 上游：<https://github.com/coleifer/huey>
- 本地：`H/huey/storage.py:824–883`，连接、事务和自动建表；
  `884–966`，表结构、WAL、`create_tables`、入队与领取删除；
  `989–1011`，计划读取删除；
  `1039` 起，结果取出删除。

**[S3] Huey 执行、撤销、结果及序列化**

- 上游：<https://github.com/coleifer/huey>
- 本地：`H/huey/api.py:279–286`、`424–575`、`659–681`、`1111–1155`、`1280–1327`；
  `H/huey/serializer.py:19–31`；
  `H/docs/api.rst:2011–2026`；
  `H/docs/guide.rst:1339–1346,1654–1679`。

**[S4] Huey consumer、调度及停止**

- 上游：<https://github.com/coleifer/huey>
- 本地：`H/huey/consumer.py:116–199`、`294–365`、`470–540`、`611–675`；
  `H/docs/consumer.rst:148–157,276–295`。

**[S5] Huey stats 的保留与可靠性边界**

- 上游：<https://github.com/coleifer/huey>
- 本地：`H/huey/contrib/stats.py:29–110,135–235`。
- 重点：缓冲写入、失败丢弃、历史及 inflight 清理。

**[S6] APScheduler 3.11.3 元数据与维护记录**

- 上游：<https://github.com/agronholm/apscheduler>
- PyPI 核验入口：<https://pypi.org/project/APScheduler/>
- 本地：`A3/PKG-INFO:1–41`；
  `A3/docs/versionhistory.rst:7–15`。
- 本地文件清单未见 `py.typed`。

**[S7] APScheduler 3.x 存储、提交、停止与共享限制**

- 上游：<https://github.com/agronholm/apscheduler>
- 本地：`A3/docs/faq.rst:74–87`；
  `A3/docs/userguide.rst:47`；
  `A3/src/apscheduler/jobstores/sqlalchemy.py:29–85,113–189`；
  `A3/src/apscheduler/schedulers/base.py:221–239,1191–1233`；
  `A3/src/apscheduler/executors/base.py:58–76`。

**[S8] APScheduler 4.0.0a6 元数据、预发布及部署文档**

- 上游：<https://github.com/agronholm/apscheduler>
- PyPI 核验入口：<https://pypi.org/project/APScheduler/4.0.0a6/>
- 本地：`A4/PKG-INFO:1–41`；
  `A4/README.rst:11–13,38–43`；
  `A4/docs/userguide.rst:448–458,616–631,658–677`；
  `A4/src/apscheduler/py.typed`。

**[S9] APScheduler 4.0a6 SQLAlchemy datastore**

- 上游：<https://github.com/agronholm/apscheduler>
- 本地：`A4/src/apscheduler/datastores/sqlalchemy.py:148–190,232–266,333–440`；
  `881–1009`，领取与类型名额；
  `1038–1104`，释放、删除及结果消费；
  `1140–1211`，abandoned 与过期清理。
- 默认 serializer：`A4/src/apscheduler/datastores/base.py:28–39`。

**[S10] APScheduler 4.0a6 运行与取消**

- 上游：<https://github.com/agronholm/apscheduler>
- 本地：`A4/src/apscheduler/_schedulers/sync.py:32–88`；
  `A4/src/apscheduler/_schedulers/async_.py:151–153,825–835,1118–1208`；
  `A4/src/apscheduler/executors/thread.py:23–31`。

**[S11] persist-queue 1.1.0 元数据与类型标注**

- 上游：<https://github.com/peter-wangxu/persist-queue>
- PyPI 核验入口：<https://pypi.org/project/persist-queue/>
- 本地：`P/setup.py:7–13,17–52`；
  `P/persist_queue.egg-info/requires.txt:1–10`；
  `P/LICENSE:1–28`；
  `P/README.rst:42–59`；
  `P/persistqueue/py.typed`。

**[S12] persist-queue 领取、恢复、确认与 SQLite 存储**

- 上游：<https://github.com/peter-wangxu/persist-queue>
- 本地：`P/persistqueue/sqlackqueue.py:15–81,125–181,212–341`；
  `P/persistqueue/sqlbase.py:18–42,109–143,198–202,237–268,361–445`；
  `P/persistqueue/serializers/json.py:24–34,49–59`。
- 重点：构造时恢复、未确认状态、默认十秒等待、缓存计数及独立数据库连接。

**[S13] litequeue 0.14 元数据与文档**

- 上游：<https://github.com/litements/litequeue>
- PyPI 核验入口：<https://pypi.org/project/litequeue/>
- 本地：`L/pyproject.toml:1–23`；
  `L/LICENSE:1–21`；
  `L/README.md:238–267,287–300`。
- 本地文件清单未见 `py.typed`。

**[S14] litequeue 同库限制、领取、恢复与迁移**

- 上游：<https://github.com/litements/litequeue>
- 本地：`L/src/litequeue/__init__.py:102–158,263–419`；
  `554–615`，领取；
  `668–818`，确认、失败、查询锁定和重投；
  `873–887,918–936`，统计与清理相关接口；
  `L/src/litequeue/migrations.py:11–79,82–148`。
- 同库拒绝检查尤其见 `__init__.py:329–353`；`synchronous=NORMAL` 见 `388–395`。

**[S15] DBOS 3.3.0 元数据**

- 上游：<https://github.com/dbos-inc/dbos-transact-py>
- PyPI 核验入口：<https://pypi.org/project/dbos/>
- 本地：`D/PKG-INFO:1–56`；
  `D/pyproject.toml:1–60`；
  `D/dbos/py.typed`。

**[S16] DBOS SQLite、schema、同步事务入队与序列化**

- 上游：<https://github.com/dbos-inc/dbos-transact-py>
- 本地：`D/dbos/_sys_db_sqlite.py:17–135,223–224`；
  `D/dbos/_client.py:265–280,335–367`；
  `D/dbos/_schemas/system_database.py:28–119`；
  `D/dbos/_serialization.py:95–108`；
  `D/dbos/_dbos_config.py:43`。

**[S17] DBOS 执行、恢复、取消与退出**

- 上游：<https://github.com/dbos-inc/dbos-transact-py>
- 本地：`D/dbos/_dbos.py:436–446,517–528,684–723,766–801,912–946`；
  `D/dbos/_sys_db.py:128–156,1203–1233,2622–2644,2987–2991,4464–4501,4715–4749`；
  `D/dbos/_recovery.py:14–47`；
  `D/dbos/_core.py:2124–2145,2245–2255,2292–2357`。

**[S18] DBOS 并发队列与定时**

- 上游：<https://github.com/dbos-inc/dbos-transact-py>
- 本地：`D/dbos/_client.py:369–400`；
  `D/dbos/_queue.py:87–126,692–704,850–900`；
  `D/dbos/_scheduler.py:58–104,115–174`。

### 在线核验未完成的官方入口

以下网址不代表本次成功读取了页面，也不作为最新版本、发布日期或当前维护状态的证明。

**[S19] Django-Q2、Taskiq**

- <https://pypi.org/project/django-q2/>
- <https://github.com/django-q2/django-q2>
- <https://django-q2.readthedocs.io/>
- <https://pypi.org/project/taskiq/>
- <https://github.com/taskiq-python/taskiq>
- <https://taskiq-python.github.io/>

**[S20] RQ**

- <https://python-rq.org/>
- <https://github.com/rq/rq>

**[S21] arq**

- <https://arq-docs.helpmanual.io/>
- <https://github.com/python-arq/arq>

**[S22] Celery / Kombu SQLAlchemy transport**

- <https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html>
- <https://docs.celeryq.dev/projects/kombu/en/stable/reference/kombu.transport.sqlalchemy.html>

**[S23] Dramatiq**

- <https://dramatiq.io/guide.html>
- <https://github.com/Bogdanp/dramatiq>

**[S24] Procrastinate**

- <https://procrastinate.readthedocs.io/>
- <https://github.com/procrastinate-org/procrastinate>

**[S25] 标准库与 SQLite 官方参考**

- 文件锁：<https://docs.python.org/3.12/library/fcntl.html>
- 子进程：<https://docs.python.org/3.12/library/subprocess.html>
- 信号：<https://docs.python.org/3.12/library/signal.html>
- 单调时钟：<https://docs.python.org/3.12/library/time.html#time.monotonic>
- 时区：<https://docs.python.org/3.12/library/zoneinfo.html>
- pickle 安全说明：<https://docs.python.org/3.12/library/pickle.html>
- SQLite WAL：<https://www.sqlite.org/wal.html>
- SQLite 同步设置：<https://www.sqlite.org/pragma.html#pragma_synchronous>

**尚未完成的核验：** 本报告完成了六份本地发布源码的行为比较；联网工具未返回可读资料，因此最新版本与发布日期、当前维护活动、APScheduler 4.x 当前发布状态、django-q2/Taskiq SQLite 路线及排除项当前文档仍未完成在线确认。上述缺口限制了“最新生态调查”的完整性，但不改变已经从指定源码中确认的删除时机、恢复行为、取消边界和 litequeue 同库冲突。