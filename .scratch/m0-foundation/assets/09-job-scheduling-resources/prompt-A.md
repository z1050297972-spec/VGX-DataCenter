你在工单「作业调度资源」的工作目录 /home/shawn/桌面/robot-data-platform.wt/m0-09-job-scheduling-resources（git worktree，分支 t/m0-09-job-scheduling-resources）里写契约骨架。

先读下面这些。规划文件一律读主仓库目录 /home/shawn/桌面/robot-data-platform 里的版本：工作目录里的副本停在开分支的那一刻，可能已经过期，也可能缺少还没提交的文件。
- /home/shawn/桌面/robot-data-platform/AGENTS.md
- /home/shawn/桌面/robot-data-platform/docs/standards/CODING_STANDARDS.md（特别是第 1.4、3 条、5 时间（5.4 monotonic 与墙钟）、6.2、6.3、6.4、6.8、6.9、7.1、10.6）
- /home/shawn/桌面/robot-data-platform/docs/agents/codex-workflow.md 第 7.1 节「历次评审打回过的写法」：这些写法以前被打回过，一开始就避免
- 工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/09-job-scheduling-resources.md（Comments 里负责人已批准 K1–K3）
- 它引用的：/home/shawn/桌面/robot-data-platform/.scratch/platform-v1/issues/10-job-model.md 的 Answer（"并发与 GPU""导航层写锁"两节、场景二）、/home/shawn/桌面/robot-data-platform/docs/adr/0005-作业由独立worker执行且是导航层唯一写者.md，和 /home/shawn/桌面/robot-data-platform/GLOSSARY.md 里的作业、Worker、导航层写锁、取消
- 已合并的第 8 张（作业框架与 worker）：`src/rdp/jobs/`（尤其 `registry.py`、`records.py`、`_loop.py`、`worker.py`、`execution.py`、`progress.py`、`processes.py`、`_recovery.py`、`policy.py`）、`src/rdp/ops/worker.py`、`src/rdp/api/jobs.py`、`src/web/src/jobs/`。第 8 张工单 /home/shawn/桌面/robot-data-platform/.scratch/m0-foundation/issues/08-job-framework-worker.md 的 Comments 记了它的设计和评审结论。
- 还有：`src/rdp/infra/config.py`、`src/rdp/infra/state.py`、`src/rdp/infra/actors.py`、`src/rdp/infra/db/records.py` 的 `clear_expired_errors`（第 5 张）、`src/rdp/audit/service.py` 的 `purge_expired`（第 7 张）。

用 $enterprise-coding。这一步只交契约骨架：
1. 签名、类型和六项 docstring 写全（AGENTS.md 规则 4，CODING_STANDARDS 第 3 条）。新函数体只写 `raise NotImplementedError`（前端 `throw new Error("未实现")`）；已合并函数要改行为的，只改签名和 docstring，函数体保持现在能跑的样子，写一行注释说明待实现，不要让现有测试变红。
2. 测试清单写成跳过的测试（`pytest.skip` / `it.skip`），每个测试的 docstring 或标题写明它验证哪条契约行为。工单验收 1–7 每条都要有对应测试；GPU 用假的 `nvidia-smi`（测试里写一个脚本），不依赖真卡。
3. `make check` 跑到全绿。新表、新列的 ORM 模型和迁移 `0005` 先隔离（照第 6、7、8 张的做法：模型 `__abstract__` 或新列先不进共用 `MetaData`、迁移放 `pending/`），实现阶段再激活。

**事先批准的扩展**（工单要求的只增不改，不用为它们停下，在第 3 块列出即可）：
- `infra/actors.py` 加一个固定身份 `SYSTEM_ACTOR = ActorRef(None, "系统")`，`ActorRef` 的校验和第 7 张操作日志的操作人校验相应放开为"运维"或"系统"两个固定身份；docstring 一起改。
- `infra/config.py` 加作业配置段（GPU 列表、按类型的并发上限），`infra/state.py` 的 `StatePaths` 加示例写锁作业用的文件路径。
- 第 8 张的 `JobDefinition`、`ExecutorDependencies`、`ExecutionContext`、`configure_jobs`、`run_worker` 为本票加字段或参数；作业表加列。
- 已合并公开签名的每处改动在第 3 块逐个列出（旧签名 → 新签名，为什么）。

**执行线已定、写进契约的设计**（拿不准的写进第 4 块，不要停下）：

*资源状态要落库*
- Web 和 worker 是两个进程（ADR 0005），页面上的"等待 GPU""等待导航层写锁"、作业领到哪张卡、写锁现在被谁拿着，都由 worker 写进数据库，Web 只读数据库。领卡、写锁本身只在 worker 内存里（崩溃后从空开始，工单"风险"），数据库里的是给页面看的副本。
- 作业表加列（名字你定）：领到的 GPU 编号（结束后保留，作历史）；等待原因（空、等待 GPU、等待导航层写锁）；是否正在持有导航层写锁。等待原因和持锁标记在作业进入终态、被恢复处理时清空。等待原因不是作业状态，状态机不变。
- worker 这些写入沿用第 8 张进度写入的短锁做法：拿不到就下一轮再写，不能卡住主循环；作业终态那次写必须写成。

*并发上限*
- `JobDefinition` 加"并发上限"，默认 1；配置文件 `[jobs.concurrency]` 按类型名覆盖，上限至少 1、有具名的最大值；配置里写了没登记的类型名，启动时拒绝（同第 3 张"不认识的项拒绝启动"）。
- 取作业：恢复的作业照旧最先处理。然后按 `job_id` 顺序扫排队中的作业；某类型已到上限就跳过这一类，看别的类型（K3：同类严格按提交顺序，不同类互不阻挡）。同类里排在前面的作业因为等 GPU 没开始，同类后面的也不越过它。
- 第 8 张的 `WORKER_CONCURRENCY = 1` 去掉。worker 同时跑多个执行线程，每个线程各自的取消、监视和回收沿用第 8 张的语义；停止预算 30 秒对所有线程共用，超预算保锁的规则不变。

*GPU 名额*
- `JobDefinition` 加"需要 GPU"（布尔，默认否）。配置 `[jobs] gpus = [0, 1]`（K1，默认两张都用；空列表表示平台不用 GPU）。
- 需要 GPU 的作业：领取时同时领一张空闲的卡（编号最小的空卡），在领取事务里记下卡号；没有空卡就留在排队中，等待原因记"等待 GPU"。平台不用 GPU（空列表）时，需要 GPU 的作业照常领取后以"外部失败"结束，诊断写明配置里没有可用的卡，不无限排队。
- 卡在作业结束时（完成、失败、取消、被停止）还回去，用 `finally` 一类的结构保证，测试覆盖每种结束方式。
- 领卡后、执行前用 `nvidia-smi` 核对这张卡在：命令路径由依赖注入（测试给假的），调用有超时（具名常量），`nvidia-smi` 报错、超时或者看不到这张卡，作业以"外部失败"结束（`ExternalError`，诊断带卡号和 `nvidia-smi` 的 stderr 尾部），不改用 CPU，卡照样还回去。
- worker 启动时用同一个核对函数检查配置里的每张卡：不在的记 ERROR 写进 `worker.log`，worker 继续运行（不需要 GPU 的作业还要跑）。
- 外部进程：作业持有 GPU 时，第 8 张的外部进程入口自动给子进程设置 `CUDA_VISIBLE_DEVICES=<卡号>` 和 `CUDA_DEVICE_ORDER=PCI_BUS_ID`（后者保证编号和 `nvidia-smi` 一致），作业类型不自己拼环境变量。作业日志开头之后写一行领到的卡号。
- 孤儿外部进程（worker 被 SIGKILL 后还占着卡）不在本票处理：第 8 张已定由第 11 张的 systemd `KillMode=control-group` 清理，工单"风险"里"worker 启动时结束上一个实例留下的子进程"不做，第 4 块注明。

*导航层写锁*
- worker 进程里一把锁（`threading.Lock` 一类），整个导航层共用，由 worker 构造后注入执行上下文，不是模块级单例。
- 执行上下文提供一个入口，作业类型传入两个函数：核对、写入。框架按顺序做：拿锁（等待期间等待原因记"等待导航层写锁"，等待可被取消打断，等待用有上限的分段等待）→ 记持锁 → 调核对 → 调写入 → 放锁并清持锁标记（`finally`）。
- 核对不通过：作业类型的核对函数抛 `ConflictError`，诊断里写明"在你预览之后被作业 #N 改过"一类的原因（N 由作业类型自己查出来），作业以失败结束，写入函数不被调用。
- 写入期间不响应取消：持锁期间上报对象的检查取消不抛出，写完放锁后的下一次检查才抛出（验收 5）。写清楚 worker 停止、写入函数抛异常时锁也会放掉。
- 运维命令拿 worker 锁的事（ADR 0005）不在本票。

*定时作业*
- 代码里登记：名字、作业类型、参数、每天几点（本地时间，默认 03:00，K2）。登记表是显式对象，由 worker 入口注入，测试可以换。
- 时间语义写清楚：本机本地时区（`docs/brief/0013`，机器可能有夏令时）；"到点"指本地时间第一次不早于登记的时刻；夏令时跳过或重复的那一小时怎么处理写明并测试；判断用注入的时钟，不直接读系统时间。
- 每个定时作业每个本地日期最多提交一次，用数据库唯一约束保证（新表：定时作业名、本地日期、提交的作业编号、提交时刻），worker 重启也不会重复提交。
- 补跑（K2）：worker 启动时，某个定时作业最近一次提交距现在超过 24 小时（或者从来没提交过），马上补交一次，只补一次；之后照常按点。
- 提交走第 8 张的提交服务，提交人是 `SYSTEM_ACTOR`，写操作日志（操作人"系统"）。
- 登记两个清除作业，不是工单写的三个：
  - "清除过期报错"：调 `clear_expired_errors`，保留期取配置 `[errors] retention_days`。
  - "清除过期日志"：调第 7 张的 `purge_expired`，它在一个事务里按共同保留期同时清操作日志和登录日志（第 7 张定的：两种日志共用一个保留期、原子清除）。拆成两个作业要拆这个函数，没有行为上的好处。执行线会在骨架关卡向负责人说明。
  - 两个清除作业的恢复方式都是"重跑"（清除是幂等的），结果计数写进作业摘要（删了几条）。
- 本票不登记 M1 的统计和第 12 张的备份。

*两个演示用的作业类型*（进生产登记表，同"示例：数数"）
- "示例：占用 GPU"：需要 GPU；参数：占用秒数（有上限）。执行：用外部进程入口跑一次 `nvidia-smi`（输出进作业日志，能看到子进程只看见一张卡），然后可取消地等待。恢复方式：标记中断。
- "示例：写锁"：参数：期望值（提交时给的字符串，代表"预览时看到的状态"）。执行：拿导航层写锁，核对状态目录下示例文件的最后一行是否等于期望值（文件不存在时期望值必须为空），对不上抛冲突、诊断写明最后一行是哪个作业写的；对上了追加一行（作业编号和新值），写入前可以按参数停顿几秒（便于演示和测试重叠，有上限）。恢复方式：标记中断。不碰导航层和数据盘。

*页面*
- 作业列表和详情显示等待原因；详情显示领到的 GPU。
- 新页面"调度"（只读，所有登录账号可见，菜单加入口）：每类作业的并发上限和正在跑的数量；每张卡在给哪个作业用；导航层写锁现在被哪个作业拿着；每个定时作业下一次几点跑、上一次提交的作业和它的结果。接口路径你定，全部走第 6 张的全局鉴权。Web 需要的配置（GPU 列表、上限）由入口传给 `configure_jobs`，Web 不自己找配置文件。OpenAPI 变了用 `make api-types` 重新生成。
- 页面沿用第 8 张的轮询、诊断和账号感知客户端写法；search 参数经真实 router 测（7.1）。

*依赖方向*
- 清除作业要调 `rdp.audit` 和 `rdp.infra.db`：`rdp.jobs` → `rdp.audit` 第 8 张已允许，不用改 import-linter。如果你认为要改，写进第 3 块。

边界：
- 只改 `src/`、`tests/`。本票允许改的受保护文件：`pyproject.toml`（只在 ruff、basedpyright 需要时调整，每条写理由；依赖表不动）。
- 改动留在工作区，不要 `git add`，也不要提交。
- 不读取 `~/桌面/data_check` 和 `~/桌面/Data_Collection_System-main`，不碰 `/mnt`。不在测试里调用真的 `nvidia-smi`。
- 不安装任何东西，不访问网络（沙箱为了跑测试开了网络权限，但这张票用不到网络；评审会查运行日志，出现安装或联网的命令整轮打回）。需要新依赖时停下，在最终回复里写依赖申请（AGENTS.md 规则 7）。
- 自己在 `/tmp` 或别处建的试验文件，交付前删掉。测试只用临时目录，不碰真实的 `~/.config/rdp`、`~/.local/share/rdp`。

只有三种情况停下：要加新依赖；要改允许范围以外的受保护文件；要改已有的对外行为（HTTP 状态码、已有接口的路径和字段、已有表结构里已有的列、负责人定的决定）。上面事先批准的扩展不算。其余拿不准的照你的判断写进契约，并列进第 4 块。

为了不超时：预计 80 分钟内写不完时，停在 `make check` 全绿的位置交回，第 4 块写清还剩什么。

最终回复分四块：
1. 改动清单：每个文件一行，写做了什么。
2. `make check`：最后一次运行的命令和末尾输出原样贴出（pytest、Vitest 的 passed、skipped 数目要看得出）；再贴 `git status --porcelain --untracked-files=all`。
3. 契约变更申请、依赖申请：没有就写"无"。已合并代码里公开签名的改动逐个列出（旧签名 → 新签名，为什么）。
4. 拿不准、需要评审决定的地方。
